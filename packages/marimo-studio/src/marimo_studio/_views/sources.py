"""Authorize and update the Source documents of one view project.

Provider inspection determines which project files appear in Source and
whether each file may be edited. Studio separately owns ``view.toml`` so a
broken provider can still expose a repair path without allowing the view to
switch provider during a save.

Every read returns a content revision. A save succeeds only while that
revision, the file identity, the provider's access decision, and the surrounding
build inputs remain current. Conditional replacement and rollback preserve a
newer external edit, while conflict responses let the browser or agent keep its
unsaved buffer and retry against the latest source.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import tomlkit
from tomlkit.exceptions import ParseError

from marimo_studio._artifacts.inputs import (
    ProjectInputState,
    project_input_state,
    project_revision_snapshot,
)
from marimo_studio._artifacts.limits import PROJECT_INPUT_BUDGET
from marimo_studio._filesystem._secure_types import (
    ConditionalWriteError,
    FileIdentity,
    SecureFileError,
)
from marimo_studio._filesystem.io import reject_mutable_symlinks
from marimo_studio._filesystem.secure import (
    open_contained_file,
    secure_directory,
)
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._views.records import ViewDocument
from marimo_studio._workspace.config import (
    load_studio,
    load_studio_definition,
    materialize_studio_workspace,
    validate_view_name,
)
from marimo_studio._workspace.generation import (
    provider_free_catalog_generation,
    view_name_generation,
)
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.project_manifest import (
    VIEW_MANIFEST_DOCUMENT,
    VIEW_MANIFEST_PATH,
    decode_view_manifest,
    decode_view_provider,
)
from marimo_studio._workspace.view_owners import ensure_present_view_owner
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    SourceConflictError,
    SourceEncodingError,
    SourceNotFoundError,
    SourceTooLargeError,
    SourceValidationError,
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.errors._internal import WorkspaceInitializationError
from marimo_studio.view_providers import (
    ProjectInspection,
    ViewProject,
)
from marimo_studio.view_providers import (
    SourceDocument as SourceDocumentSpec,
)
from marimo_studio.view_providers._host import provider_registry

SOURCE_DOCUMENT_MAX_BYTES = PROJECT_INPUT_BUDGET.max_file_bytes


@dataclass(frozen=True)
class PreparedSourceWrite:
    project: ViewProject
    inspection: ProjectInspection
    input_id: str
    spec: SourceDocumentSpec
    input_state: ProjectInputState | None = None


@dataclass(frozen=True)
class OwnedViewDocument:
    """Pair one source revision with its workspace and view owners."""

    document: ViewDocument
    catalog_generation: str
    view_generation: str

    def to_dict(self) -> dict[str, object]:
        return {
            **self.document.to_dict(),
            "catalog_generation": self.catalog_generation,
            "view_generation": self.view_generation,
        }


def _view(studio: StudioWorkspace, view_name: str) -> ViewProject:
    return studio.view(view_name)


def source_path(value: str) -> PurePosixPath:
    """Return one validated Studio source path."""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SourceNotFoundError(f"Invalid Studio source path {value!r}.")
    return path


def source_spec(
    inspection: ProjectInspection,
    name: str,
    view_name: str,
) -> SourceDocumentSpec:
    """Return one document authorized by a normalized inspection."""
    relative = source_path(name)
    if relative == VIEW_MANIFEST_PATH:
        return VIEW_MANIFEST_DOCUMENT
    matches = [item for item in inspection.editor_documents if item.path == relative]
    if len(matches) != 1:
        raise SourceNotFoundError(
            f"Unknown source document {relative.as_posix()!r} in view {view_name!r}."
        )
    return matches[0]


def _revision(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


def _read(
    studio: StudioWorkspace,
    project: ViewProject,
    spec: SourceDocumentSpec,
) -> ViewDocument:
    return _read_document(studio, project.name, project.root, spec)


def _read_snapshot(
    studio: StudioWorkspace,
    project: ViewProject,
    spec: SourceDocumentSpec,
) -> tuple[ViewDocument, FileIdentity]:
    return _read_document_snapshot(studio, project.name, project.root, spec)


def _read_document(
    studio: StudioDefinition,
    view_name: str,
    root: Path,
    spec: SourceDocumentSpec,
) -> ViewDocument:
    return _read_document_snapshot(studio, view_name, root, spec)[0]


def _read_document_snapshot(
    studio: StudioDefinition,
    view_name: str,
    root: Path,
    spec: SourceDocumentSpec,
) -> tuple[ViewDocument, FileIdentity]:
    expected_root = (studio.view_root / view_name).absolute()
    if root.absolute() != expected_root:
        raise SourceNotFoundError(
            f"View project {view_name!r} is outside the Studio workspace."
        )
    path = root.joinpath(*spec.path.parts)
    try:
        reject_mutable_symlinks(studio.notebook.parent, {path})
    except ConfigurationError as error:
        raise SourceNotFoundError(
            f"{spec.path.as_posix()} is unavailable in view {view_name!r}."
        ) from error
    try:
        descriptor = open_contained_file(studio.notebook.parent, path)
    except OSError as error:
        raise SourceNotFoundError(
            f"{spec.path.as_posix()} is unavailable in view {view_name!r}."
        ) from error
    try:
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SourceNotFoundError(
                    f"{spec.path.as_posix()} is not a regular source document."
                )
            payload = stream.read(SOURCE_DOCUMENT_MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(payload) > SOURCE_DOCUMENT_MAX_BYTES:
            raise SourceTooLargeError(
                f"{spec.path.as_posix()} in view {view_name!r} exceeds the "
                f"{SOURCE_DOCUMENT_MAX_BYTES}-byte source limit."
            )
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise SourceNotFoundError(
                f"{spec.path.as_posix()} changed while Studio read it."
            )
        content = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceEncodingError(
            f"{spec.path.as_posix()} in view {view_name!r} must be UTF-8 text."
        ) from error
    except OSError as error:
        raise SourceNotFoundError(
            f"{spec.path.as_posix()} is unavailable in view {view_name!r}."
        ) from error
    return (
        ViewDocument(
            spec.path,
            spec.language,
            spec.access,
            content,
            _revision(content),
        ),
        FileIdentity(
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            hashlib.sha256(payload).digest(),
            False,
        ),
    )


def _manifest_root(studio: StudioDefinition, view_name: str) -> Path:
    try:
        validate_view_name(view_name)
    except ConfigurationError as error:
        raise SourceNotFoundError(f"Unknown view {view_name!r}.") from error
    root = studio.view_root / view_name
    manifest = root / VIEW_MANIFEST_PATH.name
    reject_mutable_symlinks(studio.notebook.parent, {studio.view_root, root, manifest})
    if root.is_symlink() or not root.is_dir():
        raise SourceNotFoundError(f"Unknown view {view_name!r}.")
    return root.absolute()


def _read_view_manifest_locked(
    studio: StudioDefinition,
    view_name: str,
) -> ViewDocument:
    return _read_view_manifest_snapshot_locked(studio, view_name)[0]


def _read_view_manifest_snapshot_locked(
    studio: StudioDefinition,
    view_name: str,
) -> tuple[ViewDocument, FileIdentity]:
    return _read_document_snapshot(
        studio,
        view_name,
        _manifest_root(studio, view_name),
        VIEW_MANIFEST_DOCUMENT,
    )


def _conflict_revision(
    studio: StudioDefinition,
    view_name: str,
    root: Path,
    spec: SourceDocumentSpec,
) -> str | None:
    try:
        return _read_document(studio, view_name, root, spec).revision
    except (MarimoStudioError, OSError):
        return None


def read_view_manifest(
    studio: StudioDefinition,
    view_name: str,
) -> ViewDocument:
    """Read the core manifest independently of provider inspection."""
    return read_view_manifest_with_owner(studio, view_name).document


def _manifest_owner_generations(
    studio: StudioDefinition,
    view_name: str,
) -> tuple[str, str]:
    _validate_source_view_name(view_name)
    try:
        workspace = materialize_studio_workspace(studio)
    except (MarimoStudioError, OSError):
        workspace = None
    if workspace is not None:
        if view_name in workspace.view_generations:
            return (
                workspace.catalog_generation,
                workspace.view_generations[view_name],
            )
        target = studio.view_root / view_name
        if not target.is_dir() or not (target / VIEW_MANIFEST_PATH.name).is_file():
            raise ViewGenerationConflictError(view_name, None)
    target = studio.view_root / view_name
    if not target.is_dir() or not (target / VIEW_MANIFEST_PATH.name).is_file():
        raise ViewGenerationConflictError(view_name, None)
    try:
        ensure_present_view_owner(studio.view_root, view_name)
        return (
            provider_free_catalog_generation(studio),
            view_name_generation(studio.view_root, view_name),
        )
    except OSError as error:
        raise ViewGenerationConflictError(view_name, None) from error


def _require_source_owner(
    studio: StudioDefinition,
    view_name: str,
    *,
    expected_catalog_generation: str | None,
    expected_generation: str | None,
) -> None:
    catalog_generation, current_generation = _manifest_owner_generations(
        studio,
        view_name,
    )
    if expected_generation is not None and current_generation != expected_generation:
        raise ViewGenerationConflictError(view_name, current_generation)
    if (
        expected_catalog_generation is not None
        and catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()


def _reload_source_owner(
    studio: StudioDefinition,
    view_name: str,
    *,
    expected_catalog_generation: str | None,
    expected_generation: str | None,
) -> StudioDefinition:
    current = load_studio_definition(studio.config_path)
    if current.view_root != studio.view_root:
        raise WorkspaceGenerationConflictError()
    _require_source_owner(
        current,
        view_name,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
    )
    return current


def admit_source_owner(
    target: str | Path,
    view_name: str,
    *,
    expected_catalog_generation: str | None,
    expected_generation: str | None,
) -> None:
    """Admit a source mutation through provider-free owner records."""
    _validate_source_view_name(view_name)
    studio = load_studio_definition(target)
    with (
        workspace_catalog_lock(studio.view_root),
        view_mutation_lock(studio.view_root, view_name),
    ):
        _reload_source_owner(
            studio,
            view_name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )


def read_view_manifest_with_owner(
    studio: StudioDefinition,
    view_name: str,
) -> OwnedViewDocument:
    """Read the core manifest with the owners observed under its view lock."""
    _validate_source_view_name(view_name)
    with (
        workspace_catalog_lock(studio.view_root),
        view_mutation_lock(studio.view_root, view_name),
    ):
        current = load_studio_definition(studio.config_path)
        if current.view_root != studio.view_root:
            raise WorkspaceGenerationConflictError()
        before_catalog, before_view = _manifest_owner_generations(
            current,
            view_name,
        )
        document = _read_view_manifest_locked(current, view_name)
        catalog_generation, view_generation = _manifest_owner_generations(
            current,
            view_name,
        )
        if view_generation != before_view:
            raise ViewGenerationConflictError(view_name, view_generation)
        if catalog_generation != before_catalog:
            raise WorkspaceGenerationConflictError()
        return OwnedViewDocument(
            document,
            catalog_generation,
            view_generation,
        )


def _validate_source_view_name(view_name: str) -> None:
    try:
        validate_view_name(view_name)
    except ConfigurationError as error:
        raise SourceNotFoundError(f"Unknown Studio view {view_name!r}.") from error


def _validate_view_manifest(
    root: Path,
    content: str,
    expected_provider: str | None,
) -> None:
    manifest = root / VIEW_MANIFEST_PATH.name
    try:
        document = tomlkit.parse(content)
        provider, _options = decode_view_manifest(
            document.unwrap(),
            manifest,
        )
        if expected_provider is not None and provider != expected_provider:
            raise SourceValidationError(
                "A view keeps one provider. Create another view with the "
                "desired starter."
            )
    except (ConfigurationError, OSError, ValueError, ParseError) as error:
        raise SourceValidationError(str(error)) from error


def _current_view_provider(content: str, manifest: Path) -> str | None:
    try:
        document = tomlkit.parse(content)
        return decode_view_provider(document.unwrap(), manifest)
    except (ConfigurationError, ParseError):
        return None


def write_view_manifest(
    studio: StudioDefinition,
    view_name: str,
    content: str,
    expected_revision: str,
    expected_provider: str | None = None,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewDocument:
    """Validate and conditionally replace one core view manifest."""
    if len(content.encode("utf-8")) > SOURCE_DOCUMENT_MAX_BYTES:
        raise SourceTooLargeError(
            f"view.toml exceeds the {SOURCE_DOCUMENT_MAX_BYTES}-byte source limit."
        )
    with (
        workspace_catalog_lock(studio.view_root),
        view_mutation_lock(studio.view_root, view_name),
    ):
        if expected_generation is not None or expected_catalog_generation is not None:
            studio = _reload_source_owner(
                studio,
                view_name,
                expected_catalog_generation=expected_catalog_generation,
                expected_generation=expected_generation,
            )
        current, expected_identity = _read_view_manifest_snapshot_locked(
            studio,
            view_name,
        )
        if expected_generation is not None or expected_catalog_generation is not None:
            studio = _reload_source_owner(
                studio,
                view_name,
                expected_catalog_generation=expected_catalog_generation,
                expected_generation=expected_generation,
            )
        if current.revision != expected_revision:
            raise SourceConflictError(current.path.as_posix(), current.revision)
        if current.content == content:
            return current
        root = _manifest_root(studio, view_name)
        current_provider = _current_view_provider(
            current.content,
            root / VIEW_MANIFEST_PATH.name,
        )
        if (
            expected_provider is not None
            and current_provider is not None
            and current_provider != expected_provider
        ):
            raise SourceValidationError("The view provider changed before this edit.")
        retained_provider = current_provider or expected_provider
        _validate_view_manifest(
            root,
            content,
            retained_provider,
        )
        manifest = root / VIEW_MANIFEST_PATH.name
        try:
            with secure_directory(root) as files:
                if (
                    expected_generation is not None
                    or expected_catalog_generation is not None
                ):
                    studio = _reload_source_owner(
                        studio,
                        view_name,
                        expected_catalog_generation=expected_catalog_generation,
                        expected_generation=expected_generation,
                    )
                    if _manifest_root(studio, view_name) != root:
                        raise WorkspaceGenerationConflictError()
                files.ensure_attached()
                files.replace_file_if_identity(
                    manifest,
                    content.encode(),
                    expected_identity,
                )
                files.ensure_attached()
        except ConditionalWriteError as error:
            raise SourceConflictError(
                VIEW_MANIFEST_PATH.as_posix(),
                _conflict_revision(
                    studio,
                    view_name,
                    root,
                    VIEW_MANIFEST_DOCUMENT,
                ),
                external_recovery=(
                    str(error.recovery) if error.recovery is not None else None
                ),
            ) from error
        except OSError as error:
            raise SourceConflictError(
                VIEW_MANIFEST_PATH.as_posix(),
                _conflict_revision(
                    studio,
                    view_name,
                    root,
                    VIEW_MANIFEST_DOCUMENT,
                ),
            ) from error
        written = _read_view_manifest_locked(studio, view_name)
        if written.content != content:
            raise SourceConflictError(written.path.as_posix(), written.revision)
        return written


def _current_project(
    studio: StudioWorkspace,
    expected: ViewProject,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> tuple[StudioWorkspace, ViewProject]:
    expected = provider_registry().validate_project(expected)
    try:
        current_studio = load_studio(studio.config_path)
    except WorkspaceInitializationError as error:
        raise ViewGenerationConflictError(expected.name, None) from error
    current_generation = current_studio.view_generations.get(expected.name)
    if expected_generation is not None and current_generation != expected_generation:
        raise ViewGenerationConflictError(expected.name, current_generation)
    if (
        expected_catalog_generation is not None
        and current_studio.catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()
    current = provider_registry().validate_project(_view(current_studio, expected.name))
    if (
        current.root != expected.root
        or current.provider != expected.provider
        or dict(current.options) != dict(expected.options)
    ):
        raise SourceConflictError(expected.manifest.name, None)
    return current_studio, current


def read_source(
    studio: StudioWorkspace,
    view_name: str,
    name: str,
) -> ViewDocument:
    """Read one provider-discovered source document."""
    return read_source_with_owner(studio, view_name, name).document


def read_source_with_owner(
    studio: StudioWorkspace,
    view_name: str,
    name: str,
) -> OwnedViewDocument:
    """Read one provider document with its current catalog and view owners."""
    if source_path(name) == VIEW_MANIFEST_PATH:
        return read_view_manifest_with_owner(studio, view_name)
    project = _view(studio, view_name)
    inspection = inspect_view_project_sync(project)
    return read_project_source_with_owner(
        studio,
        project,
        source_spec(inspection, name, project.name),
    )


def read_project_source(
    studio: StudioWorkspace,
    project: ViewProject,
    spec: SourceDocumentSpec,
) -> ViewDocument:
    """Read a document authorized by the current shared project catalog."""
    return read_project_source_with_owner(studio, project, spec).document


def read_project_source_with_owner(
    studio: StudioWorkspace,
    project: ViewProject,
    spec: SourceDocumentSpec,
) -> OwnedViewDocument:
    """Read an authorized document with owners captured under its view lock."""
    if spec.path == VIEW_MANIFEST_PATH:
        return read_view_manifest_with_owner(studio, project.name)
    with (
        workspace_catalog_lock(studio.view_root),
        view_mutation_lock(studio.view_root, project.name),
    ):
        current_studio, current = _current_project(studio, project)
        document = _read(current_studio, current, spec)
        _current_project(
            current_studio,
            current,
            expected_catalog_generation=current_studio.catalog_generation,
            expected_generation=current_studio.view_generations[project.name],
        )
        return OwnedViewDocument(
            document,
            current_studio.catalog_generation,
            current_studio.view_generations[project.name],
        )


def write_source(
    studio: StudioWorkspace,
    view_name: str,
    name: str,
    content: str,
    expected_revision: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewDocument:
    """Replace one editable document when its loaded ETag is current."""
    if source_path(name) == VIEW_MANIFEST_PATH:
        return write_view_manifest(
            studio,
            view_name,
            content,
            expected_revision,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
    project = _view(studio, view_name)
    inspection = inspect_view_project_sync(project)
    provider = provider_registry().get(project.provider)
    try:
        spec = source_spec(inspection, name, project.name)
    except SourceNotFoundError:
        with (
            workspace_catalog_lock(studio.view_root),
            view_mutation_lock(studio.view_root, project.name),
        ):
            studio, project = _current_project(studio, project)
        inspection = inspect_view_project_sync(project)
        provider = provider_registry().get(project.provider)
        spec = source_spec(inspection, name, project.name)
    try:
        snapshot = project_revision_snapshot(
            project,
            inspection,
            provider.provenance(inspection),
        )
    except (ConfigurationError, OSError, ValueError) as error:
        with (
            workspace_catalog_lock(studio.view_root),
            view_mutation_lock(studio.view_root, project.name),
        ):
            revision = _conflict_revision(
                studio,
                project.name,
                project.root,
                spec,
            )
        if revision is not None:
            raise SourceConflictError(spec.path.as_posix(), revision) from error
        raise SourceNotFoundError(
            f"Unknown source document {spec.path.as_posix()!r} "
            f"in view {project.name!r}."
        ) from error
    return write_project_source(
        studio,
        PreparedSourceWrite(
            project,
            inspection,
            snapshot.revision,
            spec,
            snapshot.state,
        ),
        content,
        expected_revision,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
    )


def write_project_source(
    studio: StudioWorkspace,
    prepared: PreparedSourceWrite,
    content: str,
    expected_revision: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> ViewDocument:
    """Conditionally replace one document through a same-directory rename."""
    project = prepared.project
    expected_spec = prepared.spec
    if expected_spec.path == VIEW_MANIFEST_PATH:
        return write_view_manifest(
            studio,
            project.name,
            content,
            expected_revision,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
    if len(content.encode("utf-8")) > SOURCE_DOCUMENT_MAX_BYTES:
        raise SourceTooLargeError(
            f"{expected_spec.path.as_posix()} exceeds the "
            f"{SOURCE_DOCUMENT_MAX_BYTES}-byte source limit."
        )
    provider = provider_registry().get(project.provider)
    try:
        captured = (
            project_revision_snapshot(
                project,
                prepared.inspection,
                provider.provenance(prepared.inspection),
            )
            if prepared.input_state is None
            else None
        )
    except (ConfigurationError, OSError, ValueError) as error:
        raise SourceConflictError(expected_spec.path.as_posix(), None) from error
    input_id = captured.revision if captured is not None else prepared.input_id
    input_state = captured.state if captured is not None else prepared.input_state
    assert input_state is not None
    if input_id != prepared.input_id:
        raise SourceConflictError(expected_spec.path.as_posix(), None)
    with (
        workspace_catalog_lock(studio.view_root),
        view_mutation_lock(studio.view_root, project.name),
    ):
        current_studio, current_project = _current_project(
            studio,
            project,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
        current_spec = source_spec(
            prepared.inspection,
            expected_spec.path.as_posix(),
            current_project.name,
        )
        current, expected_identity = _read_snapshot(
            current_studio,
            current_project,
            current_spec,
        )
        if current_spec != expected_spec:
            raise SourceConflictError(current.path.as_posix(), current.revision)
        if current.access != "edit":
            raise SourceNotFoundError(
                f"{current.path.as_posix()} in view "
                f"{current_project.name!r} is read-only."
            )
        if current.revision != expected_revision:
            raise SourceConflictError(current.path.as_posix(), current.revision)
        if content == current.content:
            return current
        path = current_project.root.joinpath(*current.path.parts)
        try:
            with secure_directory(current_project.root) as files:
                try:
                    current_input_state = project_input_state(
                        current_project,
                        prepared.inspection,
                        files=files,
                    )
                except (ConfigurationError, OSError, ValueError) as error:
                    raise SourceConflictError(
                        current.path.as_posix(), current.revision
                    ) from error
                if current_input_state != input_state:
                    raise SourceConflictError(current.path.as_posix(), current.revision)
                written_identity = files.replace_file_if_identity(
                    path,
                    content.encode(),
                    expected_identity,
                )
                try:
                    final_input_state = project_input_state(
                        current_project,
                        prepared.inspection,
                        files=files,
                    )
                    if not _authorization_inputs_match(
                        input_state,
                        final_input_state,
                        current.path,
                    ):
                        raise SourceConflictError(
                            current.path.as_posix(), current.revision
                        )
                except (
                    ConfigurationError,
                    OSError,
                    SourceConflictError,
                    ValueError,
                ) as error:
                    if isinstance(error, SecureFileError):
                        try:
                            files.ensure_attached()
                        except SecureFileError:
                            raise ConfigurationError(str(error)) from error
                    files.replace_file_if_identity(
                        path,
                        current.content.encode(),
                        written_identity,
                    )
                    if isinstance(error, SourceConflictError):
                        raise
                    raise SourceConflictError(
                        current.path.as_posix(), current.revision
                    ) from error
        except ConditionalWriteError as error:
            raise SourceConflictError(
                current.path.as_posix(),
                _conflict_revision(
                    current_studio,
                    current_project.name,
                    current_project.root,
                    current_spec,
                ),
                external_recovery=(
                    str(error.recovery) if error.recovery is not None else None
                ),
            ) from error
        except OSError as error:
            raise SourceConflictError(
                current.path.as_posix(),
                _conflict_revision(
                    current_studio,
                    current_project.name,
                    current_project.root,
                    current_spec,
                ),
            ) from error
        written = _read(current_studio, current_project, current_spec)
        if written.content != content:
            raise SourceConflictError(written.path.as_posix(), written.revision)
        return written


def _authorization_inputs_match(
    expected: ProjectInputState,
    current: ProjectInputState,
    target: PurePosixPath,
) -> bool:
    return expected.paths == current.paths and all(
        expected.files[path] == current.files[path]
        for path in expected.paths
        if path != target
    )
