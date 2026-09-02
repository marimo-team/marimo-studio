"""Export one view as a self-contained WebAssembly site.

Static export combines a production artifact, saved notebook source, packaged
Studio browser runtime, notebook public files, and the same mount and runtime
configuration used by live delivery. The exported page executes notebook logic
in a browser worker and can render the authored cells, values, outputs, and
controls without a Python server.

Studio verifies artifact membership, reserved routes, case-insensitive path
collisions, source and configuration stability, runtime release identity, and
every copied asset. The complete bundle is written to a private staging
directory before it can replace the destination. The output transaction
protects notebook and view source and preserves the previous bundle or a
recoverable copy when replacement fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import marimo_studio._delivery.assets as _assets
from marimo_studio._artifacts.inputs import project_revision
from marimo_studio._artifacts.limits import (
    ARTIFACT_OUTPUT_BUDGET,
    FileBudgetTracker,
)
from marimo_studio._artifacts.records import ViewArtifact
from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._composition import create_export_adapters
from marimo_studio._delivery.export_output import commit_bundle as _commit_bundle
from marimo_studio._delivery.export_output import (
    output_filesystem as _output_filesystem,
)
from marimo_studio._delivery.export_output import output_target as _target
from marimo_studio._delivery.export_output import (
    temporary_directory as _temporary_directory,
)
from marimo_studio._delivery.export_output import validate_output as _validate_output
from marimo_studio._delivery.html import runtime_document
from marimo_studio._delivery.ports import ExportAdapters
from marimo_studio._delivery.runtime_config import (
    RuntimeConfigInputs,
    encode_runtime_config,
    runtime_projection_revision,
)
from marimo_studio._filesystem.secure import (
    SecureDirectory,
    secure_directory,
)
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._projections.resolution import (
    projection_policy,
    projection_targets,
)
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio._views.build import publish_view
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._workspace.config import load_studio
from marimo_studio._workspace.models import (
    RESERVED_VIEW_ASSET_NAMES,
    StudioWorkspace,
)
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio.errors import (
    MarimoStudioError,
    StaticExportError,
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers._host import provider_registry

RUNTIME_ID = "wasm"
SUPPORT_ROOT = Path("_marimo-studio")


@dataclass(frozen=True)
class StaticExportResult:
    """Describe one generated static view bundle."""

    notebook: Path
    view: str
    output: Path
    document: PurePosixPath
    files: int

    @property
    def entrypoint(self) -> Path:
        """Return the output path for the provider's artifact document."""
        return self.output.joinpath(*self.document.parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "runtime": RUNTIME_ID,
            "output": str(self.output),
            "entrypoint": str(self.entrypoint),
            "files": self.files,
        }


@dataclass(frozen=True)
class _AssetCopy:
    destination: Path
    owner: str
    sha256: str
    mode: int | None
    artifact_path: PurePosixPath | None = None


def _file_stamp(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


def _destination_key(path: Path) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in path.parts)


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _projection_error(resolved: ResolvedStudio, view_name: str) -> None:
    diagnostics = resolved.views[view_name].diagnostics
    if not diagnostics:
        return
    first = diagnostics[0]
    location = f"{first.source}:{first.line}:{first.column}"
    remaining = len(diagnostics) - 1
    suffix = f" and {remaining} more" if remaining else ""
    raise StaticExportError(
        f"View {view_name!r} has unresolved projections: "
        f"{first.message} ({location}){suffix}. "
        f"Run `marimo-studio validate {view_name} "
        f"--target {resolved.workspace.notebook} "
        "--level static` for repair details."
    )


def _runtime_config(
    adapters: ExportAdapters,
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    view_name: str,
    artifact: ViewArtifact,
    document: str,
    notebook_source: str,
) -> tuple[str, bytes]:
    projection = adapters.browser.project(
        studio.notebook,
        notebook_source,
    )
    cell_refs = resolved.runtime_cell_refs(None)
    document_parent = artifact.document.parent
    root_prefix = (
        "./"
        if document_parent == PurePosixPath(".")
        else "../" * len(document_parent.parts)
    )
    support_url = f"{root_prefix}{SUPPORT_ROOT.as_posix()}/views/{view_name}"
    marimo_config = adapters.runtime_config(studio.notebook)
    targets = projection_targets(resolved.symbols, artifact.mounts)
    mounts = tuple(site.to_dict() for site in artifact.mounts)
    policy = projection_policy()
    source_revision = _digest(
        notebook_source,
        studio.config_path.read_text(encoding="utf-8"),
    )
    projection_revision = runtime_projection_revision(
        source_revision=source_revision,
        view=view_name,
        runtime_id=RUNTIME_ID,
        runtime_instance=projection.instance,
        mounts=mounts,
        projection_targets=targets,
        projection_policy=policy,
        runtime_cell_refs=cell_refs,
        diagnostics=(),
    )
    inputs = RuntimeConfigInputs(
        view=view_name,
        views=(view_name,),
        runtime_id=RUNTIME_ID,
        runtime_instance=projection.instance,
        runtime_data=projection.runtime_data(),
        root_url=root_prefix,
        public_root_url=root_prefix,
        document_root_url=root_prefix,
        support_url=support_url,
        projection_revision=projection_revision,
        show_cell_logs=studio.show_cell_logs,
        projection_targets=targets,
        mounts=mounts,
        projection_policy=policy,
        runtime_cell_refs=cell_refs,
        diagnostics=(),
        app_config=resolved.notebook.app_config,
        user_config=marimo_config.user,
        config_overrides=marimo_config.overrides,
        dev=False,
        mode="run",
    )
    runtime_fields = inputs.to_dict(revision="")
    runtime_fields.pop("revision")
    canonical_runtime = json.dumps(
        runtime_fields,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    revision = _digest(
        view_name,
        document,
        artifact.artifact_revision,
        canonical_runtime,
    )
    config = inputs.to_dict(revision=revision)
    rendered = runtime_document(
        document,
        root_url="./",
        support_url=support_url,
        assets_url=f"{root_prefix}{SUPPORT_ROOT.as_posix()}/assets",
        dev=False,
        revision=revision,
        runtime=RUNTIME_ID,
        runtime_explicit=False,
        replay=False,
        renewal_token=None,
        filename="notebook.py",
        marimo_version=projection.version,
    )
    return rendered, encode_runtime_config(config)


def _asset_files(
    source: Path,
    destination: Path,
    owner: str,
    consume: Callable[[_AssetCopy, bytes], None],
) -> list[_AssetCopy]:
    assets: list[_AssetCopy] = []
    budget = FileBudgetTracker(ARTIFACT_OUTPUT_BUDGET, owner.capitalize())
    try:
        with secure_directory(source) as filesystem:
            files = filesystem.regular_file_sizes(
                max_entries=ARTIFACT_OUTPUT_BUDGET.max_files,
            )
            for path, expected_size in files:
                relative = path.relative_to(filesystem.root)
                budget.add(relative.as_posix(), expected_size)
                descriptor = filesystem.open_file(path)
                try:
                    before = os.fstat(descriptor)
                    payload = bytearray()
                    remaining = expected_size
                    while remaining:
                        chunk = os.read(descriptor, min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        payload.extend(chunk)
                        remaining -= len(chunk)
                    grew = bool(os.read(descriptor, 1))
                    after = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                if (
                    before.st_dev != after.st_dev
                    or before.st_ino != after.st_ino
                    or before.st_mode != after.st_mode
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ctime_ns != after.st_ctime_ns
                    or len(payload) != expected_size
                    or grew
                ):
                    raise StaticExportError(
                        f"Static export source changed while it was read: {path}"
                    )
                captured = bytes(payload)
                asset = _AssetCopy(
                    destination=destination / relative,
                    owner=owner,
                    sha256=hashlib.sha256(captured).hexdigest(),
                    mode=stat.S_IMODE(before.st_mode),
                )
                consume(asset, captured)
                assets.append(asset)
            filesystem.ensure_attached()
    except StaticExportError:
        raise
    except MarimoStudioError as error:
        raise StaticExportError(str(error)) from error
    except OSError as error:
        raise StaticExportError(
            f"Could not read static export source: {source}"
        ) from error
    return assets


def _claim_asset(
    files: dict[tuple[str, ...], tuple[str, Path]],
    directories: dict[tuple[str, ...], tuple[str, Path]],
    destination: Path,
    owner: str,
) -> None:
    key = _destination_key(destination)
    conflict = files.get(key) or directories.get(key)
    if conflict is None:
        conflict = next(
            (
                claimed
                for index in range(1, len(key))
                if (claimed := files.get(key[:index])) is not None
            ),
            None,
        )
    if conflict is not None:
        conflict_owner, conflict_path = conflict
        raise StaticExportError(
            f"Static export paths {conflict_path.as_posix()!r} and "
            f"{destination.as_posix()!r} are owned by both {conflict_owner} and "
            f"{owner}. Rename the view asset."
        )
    files[key] = owner, destination
    for index in range(1, len(key)):
        directories.setdefault(key[:index], (owner, Path(*destination.parts[:index])))


def _asset_plan(
    studio: StudioWorkspace,
    view_name: str,
    lease: ArtifactLease,
    filesystem: SecureDirectory | None = None,
) -> tuple[_AssetCopy, ...]:
    artifact = lease.artifact
    try:
        lease.verify_membership()
    except MarimoStudioError as error:
        raise StaticExportError(str(error)) from error
    support = SUPPORT_ROOT / "views" / view_name
    generated = [
        (Path(*artifact.document.parts), "the generated view document"),
        (Path(".nojekyll"), "the generated site marker"),
        (support / "config", "the generated runtime configuration"),
    ]
    files: dict[tuple[str, ...], tuple[str, Path]] = {}
    directories: dict[tuple[str, ...], tuple[str, Path]] = {}
    for destination, owner in generated:
        _claim_asset(files, directories, destination, owner)

    copies: list[_AssetCopy] = []

    def accept(asset: _AssetCopy, payload: bytes | None = None) -> None:
        if asset.owner == f"view {view_name!r}" and (
            asset.destination.parts
            and unicodedata.normalize("NFC", asset.destination.parts[0]).casefold()
            in RESERVED_VIEW_ASSET_NAMES
        ):
            raise StaticExportError(
                f"View asset path {asset.destination.as_posix()!r} uses a reserved "
                "Marimo or Studio route. Rename the view asset."
            )
        _claim_asset(files, directories, asset.destination, asset.owner)
        if filesystem is not None:
            destination = filesystem.root / asset.destination
            filesystem.ensure_parent(destination)
            if asset.artifact_path is not None:
                try:
                    content = lease.read_bytes(asset.artifact_path)
                except MarimoStudioError as error:
                    raise StaticExportError(str(error)) from error
                filesystem.atomic_write(destination, content, mode=0o644)
            elif payload is not None and asset.mode is not None:
                filesystem.atomic_write(destination, payload, mode=asset.mode)
            else:
                raise RuntimeError("Static export asset has no captured payload")
        copies.append(asset)

    _asset_files(
        _assets.runtime_assets_path(),
        SUPPORT_ROOT / "assets",
        "the Studio runtime",
        accept,
    )
    for item in artifact.files:
        if item.path == artifact.document:
            continue
        accept(
            _AssetCopy(
                destination=Path(*item.path.parts),
                owner=f"view {view_name!r}",
                sha256=item.sha256,
                mode=None,
                artifact_path=item.path,
            )
        )
    public = studio.notebook.parent / "public"
    if public.is_dir():
        _asset_files(
            public,
            Path("public"),
            "the notebook public directory",
            accept,
        )
    return tuple(copies)


def _write_bundle(
    filesystem: SecureDirectory,
    adapters: ExportAdapters,
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    view_name: str,
    lease: ArtifactLease,
    document: str,
    notebook_source: str,
    notebook_stamp: tuple[int, int, int, int],
    config_stamp: tuple[int, int, int, int],
) -> int:
    output = filesystem.root
    artifact = lease.artifact
    rendered, config = _runtime_config(
        adapters,
        studio,
        resolved,
        view_name,
        artifact,
        document,
        notebook_source,
    )
    support = output / SUPPORT_ROOT
    view_support = support / "views" / view_name

    assets = _asset_plan(studio, view_name, lease, filesystem)

    entrypoint = output.joinpath(*artifact.document.parts)
    filesystem.ensure_parent(entrypoint)
    filesystem.atomic_write(entrypoint, rendered.encode(), mode=0o644)
    config_path = view_support / "config"
    filesystem.ensure_parent(config_path)
    filesystem.atomic_write(
        config_path,
        config,
        mode=0o644,
    )
    filesystem.atomic_write(output / ".nojekyll", b"", mode=0o644)
    try:
        lease.verify()
        project = provider_registry().validate_project(studio.views[view_name])
        inspection = inspect_view_project_sync(project)
        stable = (
            assets == _asset_plan(studio, view_name, lease)
            and artifact.project_revision
            == project_revision(
                project,
                inspection,
                provider_registry().get(project.provider).provenance(inspection),
            )
            and document == lease.read_text(artifact.document)
            and notebook_source == studio.notebook.read_text(encoding="utf-8")
            and notebook_stamp == _file_stamp(studio.notebook)
            and config_stamp == _file_stamp(studio.config_path)
        )
    except (OSError, MarimoStudioError) as error:
        raise_process_cleanup(error)
        stable = False
    if not stable:
        raise StaticExportError(
            "The static export sources changed while the bundle was written. "
            "Run the export again."
        )
    filesystem.ensure_attached()
    return len(assets) + 3


def export_view(
    target: str | Path,
    output: str | Path,
    *,
    view: str | None = None,
    force: bool = False,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StaticExportResult:
    """Export one configured view as an HTTP-hosted WebAssembly site."""
    adapters = create_export_adapters()
    studio = load_studio(target)
    notebook_stamp = _file_stamp(studio.notebook)
    config_stamp = _file_stamp(studio.config_path)
    selected = view or studio.default_view
    if selected not in studio.views:
        raise ViewNotFoundError(selected, available=tuple(studio.views))
    current_generation = studio.view_generations.get(selected)
    if expected_generation is not None and current_generation != expected_generation:
        raise ViewGenerationConflictError(selected, current_generation)
    if (
        expected_catalog_generation is not None
        and studio.catalog_generation != expected_catalog_generation
    ):
        raise WorkspaceGenerationConflictError()
    destination = _validate_output(Path(output), studio)
    if destination.exists() and not force:
        raise StaticExportError(
            f"Output already exists: {destination}. Pass --force to replace it."
        )

    try:
        lease = publish_view(
            studio.views[selected],
            "production",
            expected_generation=expected_generation,
        )
    except (ViewGenerationConflictError, WorkspaceGenerationConflictError):
        raise
    except MarimoStudioError as error:
        raise StaticExportError(str(error)) from error
    with lease:
        artifact = lease.artifact
        try:
            document = lease.read_text(artifact.document)
        except MarimoStudioError as error:
            raise StaticExportError(str(error)) from error
        notebook_source = studio.notebook.read_text(encoding="utf-8")
        resolved = resolve_studio(
            studio,
            view_name=selected,
            published_mounts={selected: artifact.mounts},
        )
        _projection_error(resolved, selected)
        with _output_filesystem(destination) as filesystem:
            output_target = _target(filesystem, destination, force=force)
            staging_root = _temporary_directory(
                filesystem,
                "export",
            )
            staged = staging_root / "bundle"
            filesystem.create_directory(staged)
            try:
                with secure_directory(staged) as bundle_files:
                    files = _write_bundle(
                        bundle_files,
                        adapters,
                        studio,
                        resolved,
                        selected,
                        lease,
                        document,
                        notebook_source,
                        notebook_stamp,
                        config_stamp,
                    )
                with (
                    workspace_catalog_lock(studio.view_root),
                    view_mutation_lock(studio.view_root, selected),
                ):
                    current = load_studio(target)
                    current_generation = current.view_generations.get(selected)
                    if (
                        expected_generation is not None
                        and current_generation != expected_generation
                    ):
                        raise ViewGenerationConflictError(
                            selected,
                            current_generation,
                        )
                    if (
                        expected_catalog_generation is not None
                        and current.catalog_generation != expected_catalog_generation
                    ):
                        raise WorkspaceGenerationConflictError()
                    _commit_bundle(staged, output_target)
            finally:
                with suppress(OSError):
                    filesystem.remove_tree(staging_root)

    return StaticExportResult(
        notebook=studio.notebook,
        view=selected,
        output=destination,
        document=artifact.document,
        files=files,
    )
