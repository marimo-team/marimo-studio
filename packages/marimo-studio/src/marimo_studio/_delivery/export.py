"""Export one view as a prepared or WebAssembly static site.

Static export combines a production artifact, saved notebook source, packaged
Studio browser runtime, notebook public files, and the same mount and runtime
configuration used by live delivery. A prepared export reads notebook results
computed during export. A WebAssembly export executes notebook logic in a
browser worker.

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
import math
import os
import stat
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from marimo_export.manifest import prepared_manifest_bytes
from marimo_export.progress import CacheActivity

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
from marimo_studio._prepared.static import StaticPublication, publication_source
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

SUPPORT_ROOT = Path("_marimo-studio")
StaticRuntime = Literal["zero-python", "wasm"]
DEFAULT_STATIC_RUNTIME: StaticRuntime = "zero-python"
DEFAULT_PREPARE_TIMEOUT = 30.0


@dataclass(frozen=True)
class StaticExportResult:
    """Describe one generated static view bundle."""

    notebook: Path
    view: str
    runtime: StaticRuntime
    output: Path
    document: PurePosixPath
    files: int
    cache_activity: CacheActivity | None

    @property
    def entrypoint(self) -> Path:
        """Return the output path for the provider's artifact document."""
        return self.output.joinpath(*self.document.parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "runtime": self.runtime,
            "output": str(self.output),
            "entrypoint": str(self.entrypoint),
            "files": self.files,
            "cache_activity": (
                None if self.cache_activity is None else self.cache_activity.to_dict()
            ),
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


def _wasm_runtime_config(
    adapters: ExportAdapters,
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    view_name: str,
    artifact: ViewArtifact,
    document: str,
    notebook_source: str,
) -> tuple[str, bytes, _assets.BrowserEntryClosure]:
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
        runtime_id="wasm",
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
        runtime_id="wasm",
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
        runtime="wasm",
        runtime_explicit=False,
        replay=False,
        renewal_token=None,
        filename="notebook.py",
        marimo_version=projection.version,
    )
    return (
        rendered,
        encode_runtime_config(config),
        _assets.browser_entry_closure("runtime"),
    )


def _zero_python_runtime_config(
    adapters: ExportAdapters,
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    view_name: str,
    artifact: ViewArtifact,
    document: str,
    notebook_source: str,
    publication: StaticPublication,
) -> tuple[str, bytes, bytes, _assets.BrowserEntryClosure]:
    cell_refs = resolved.runtime_cell_refs(None)
    document_parent = artifact.document.parent
    root_prefix = (
        "./"
        if document_parent == PurePosixPath(".")
        else "../" * len(document_parent.parts)
    )
    support_url = f"{root_prefix}{SUPPORT_ROOT.as_posix()}/views/{view_name}"
    mounts = tuple(site.to_dict() for site in artifact.mounts)
    targets = projection_targets(resolved.symbols, artifact.mounts)
    policy = projection_policy()
    projection_revision = runtime_projection_revision(
        source_revision=_digest(
            notebook_source,
            studio.config_path.read_text(encoding="utf-8"),
            publication.state_space_source.digest,
        ),
        view=view_name,
        runtime_id="zero-python",
        runtime_instance=publication.instance,
        mounts=mounts,
        projection_targets=targets,
        projection_policy=policy,
        runtime_cell_refs=cell_refs,
        diagnostics=(),
    )
    marimo_config = adapters.runtime_config(studio.notebook)
    inputs = RuntimeConfigInputs(
        view=view_name,
        views=(view_name,),
        runtime_id="zero-python",
        runtime_instance=publication.instance,
        runtime_data={
            "manifestUrl": f"{support_url}/zero-python/current",
            "planDigest": publication.plan_digest,
        },
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
    revision = _digest(
        view_name,
        document,
        artifact.artifact_revision,
        publication.instance,
        json.dumps(
            runtime_fields,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    config = inputs.to_dict(revision=revision)
    closure = _assets.browser_entry_closure("zero-python")
    runtime_root = _assets.runtime_assets_path()
    entry = closure.script.relative_to(runtime_root).as_posix()
    styles = tuple(path.relative_to(runtime_root).as_posix() for path in closure.styles)
    rendered = runtime_document(
        document,
        root_url="./",
        support_url=support_url,
        assets_url=f"{root_prefix}{SUPPORT_ROOT.as_posix()}/assets",
        dev=False,
        revision=revision,
        runtime="zero-python",
        runtime_explicit=False,
        replay=False,
        renewal_token=None,
        filename="notebook.py",
        marimo_version=_assets.runtime_marimo_version(),
        runtime_entry=entry,
        runtime_styles=styles,
    )
    manifest = publication.manifest(f"./{publication.instance}/")
    return (
        rendered,
        encode_runtime_config(config),
        prepared_manifest_bytes(manifest),
        closure,
    )


def _asset_files(
    source: Path,
    destination: Path,
    owner: str,
    consume: Callable[[_AssetCopy, bytes], None],
    *,
    include: frozenset[PurePosixPath] | None = None,
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
                if (
                    include is not None
                    and PurePosixPath(relative.as_posix()) not in include
                ):
                    continue
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
    *,
    closure: _assets.BrowserEntryClosure | None,
    publication: StaticPublication | None,
    include_config: bool,
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
    ]
    if include_config:
        generated.append((support / "config", "the generated runtime configuration"))
    if publication is not None:
        generated.append(
            (support / "zero-python" / "current", "the prepared runtime manifest")
        )
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

    if closure is not None:
        runtime_root = _assets.runtime_assets_path()
        closure_paths = (closure.script, *closure.styles, *closure.assets)
        _asset_files(
            runtime_root,
            SUPPORT_ROOT / "assets",
            "the Studio runtime",
            accept,
            include=frozenset(
                PurePosixPath(path.relative_to(runtime_root).as_posix())
                for path in closure_paths
            ),
        )
    if publication is not None:
        _asset_files(
            publication.path,
            support / "zero-python" / publication.instance,
            f"prepared publication {publication.instance!r}",
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
    runtime: StaticRuntime,
    publication: StaticPublication | None,
) -> int:
    output = filesystem.root
    artifact = lease.artifact
    manifest: bytes | None = None
    if runtime == "wasm":
        rendered, config, closure = _wasm_runtime_config(
            adapters,
            studio,
            resolved,
            view_name,
            artifact,
            document,
            notebook_source,
        )
    elif publication is None:
        rendered, config, closure = document, None, None
    else:
        rendered, config, manifest, closure = _zero_python_runtime_config(
            adapters,
            studio,
            resolved,
            view_name,
            artifact,
            document,
            notebook_source,
            publication,
        )
    support = output / SUPPORT_ROOT
    view_support = support / "views" / view_name

    assets = _asset_plan(
        studio,
        view_name,
        lease,
        closure=closure,
        publication=publication,
        include_config=config is not None,
        filesystem=filesystem,
    )

    entrypoint = output.joinpath(*artifact.document.parts)
    filesystem.ensure_parent(entrypoint)
    filesystem.atomic_write(entrypoint, rendered.encode(), mode=0o644)
    if config is not None:
        config_path = view_support / "config"
        filesystem.ensure_parent(config_path)
        filesystem.atomic_write(config_path, config, mode=0o644)
    if manifest is not None:
        manifest_path = view_support / "zero-python" / "current"
        filesystem.ensure_parent(manifest_path)
        filesystem.atomic_write(manifest_path, manifest, mode=0o644)
    filesystem.atomic_write(output / ".nojekyll", b"", mode=0o644)
    try:
        lease.verify()
        project = provider_registry().validate_project(studio.views[view_name])
        inspection = inspect_view_project_sync(project)
        stable = (
            assets
            == _asset_plan(
                studio,
                view_name,
                lease,
                closure=closure,
                publication=publication,
                include_config=config is not None,
            )
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
            and (publication is None or _publication_current(publication))
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
    return len(assets) + 2 + int(config is not None) + int(manifest is not None)


def _publication_current(publication: StaticPublication) -> bool:
    try:
        publication.prepared.open().verify()
        publication.state_space_source.require_current()
    except (OSError, RuntimeError, MarimoStudioError):
        return False
    return True


def _resolve_prepare_timeout(
    runtime: StaticRuntime,
    prepare_timeout: float | None,
) -> float | None:
    if runtime == "wasm":
        if prepare_timeout is not None:
            raise ValueError(
                "prepare_timeout is only valid when runtime is 'zero-python'"
            )
        return None
    value = DEFAULT_PREPARE_TIMEOUT if prepare_timeout is None else prepare_timeout
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("prepare_timeout must be a finite positive number")
    return float(value)


def export_view(
    target: str | Path,
    output: str | Path,
    *,
    view: str | None = None,
    runtime: StaticRuntime = DEFAULT_STATIC_RUNTIME,
    force: bool = False,
    prepare_timeout: float | None = None,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StaticExportResult:
    """Export one configured view through a selected static runtime."""
    if runtime not in {"zero-python", "wasm"}:
        raise ValueError("runtime must be 'zero-python' or 'wasm'")
    resolved_prepare_timeout = _resolve_prepare_timeout(runtime, prepare_timeout)
    adapters = create_export_adapters()
    prepared_source = publication_source()
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
    destination = _validate_output(
        Path(output),
        studio,
        protected_sources=(prepared_source.protected_root(studio.notebook),),
    )
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
    publication: StaticPublication | None = None
    cache_activity: CacheActivity | None = None
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
        if runtime == "zero-python" and artifact.mounts:
            from marimo_studio._server.presentation.service import PresentationSnapshot

            source_revision = _digest(
                notebook_source,
                studio.config_path.read_text(encoding="utf-8"),
            )
            snapshot = PresentationSnapshot(
                resolved=resolved,
                view_name=selected,
                artifact=artifact,
                document=document,
                notebook_source=notebook_source,
                source_revision=source_revision,
                symbols=resolved.symbols,
                mounts=artifact.mounts,
                revision=_digest(
                    selected,
                    source_revision,
                    artifact.artifact_revision,
                ),
            )
            try:
                assert resolved_prepare_timeout is not None
                publication = prepared_source.resolve(
                    snapshot,
                    timeout=resolved_prepare_timeout,
                )
                cache_activity = publication.prepared.cache_activity
            except (OSError, RuntimeError, MarimoStudioError) as error:
                raise StaticExportError(
                    f"Could not prepare the Zero-Python publication: {error}"
                ) from error
        try:
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
                            runtime,
                            publication,
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
                            and current.catalog_generation
                            != expected_catalog_generation
                        ):
                            raise WorkspaceGenerationConflictError()
                        if (
                            notebook_stamp != _file_stamp(current.notebook)
                            or config_stamp != _file_stamp(current.config_path)
                            or (
                                publication is not None
                                and not _publication_current(publication)
                            )
                        ):
                            raise StaticExportError(
                                "The static export sources changed before publication. "
                                "Run the export again."
                            )
                        _commit_bundle(staged, output_target)
                finally:
                    with suppress(OSError):
                        filesystem.remove_tree(staging_root)
        finally:
            if publication is not None:
                publication.close()

    return StaticExportResult(
        notebook=studio.notebook,
        view=selected,
        runtime=runtime,
        output=destination,
        document=artifact.document,
        files=files,
        cache_activity=cache_activity,
    )
