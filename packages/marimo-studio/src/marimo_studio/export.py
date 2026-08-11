"""Export one custom view as a static WebAssembly site."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from marimo_studio import _assets
from marimo_studio._capabilities import ExportAdapters
from marimo_studio._composition import create_export_adapters
from marimo_studio._html import cell_host, render, runtime_document
from marimo_studio._workspace.config import load_studio
from marimo_studio._workspace.models import (
    RESERVED_VIEW_ASSET_NAMES,
    ResolvedStudio,
    StudioWorkspace,
)
from marimo_studio._workspace.templates import TemplateParser
from marimo_studio.errors import StaticExportError
from marimo_studio.types import ValueReference
from marimo_studio.workspace import resolve_studio

RUNTIME_ID = "wasm"
SUPPORT_ROOT = Path("_marimo-studio")


@dataclass(frozen=True)
class StaticExportResult:
    """Describe one generated static view bundle."""

    notebook: Path
    view: str
    output: Path
    files: int

    @property
    def entrypoint(self) -> Path:
        return self.output / "index.html"

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
    source: Path
    destination: Path
    owner: str
    stamp: tuple[int, int, int, int]


@dataclass(frozen=True)
class _OutputTarget:
    path: Path
    identity: tuple[tuple[object, ...], ...] | None


def _file_stamp(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


def _directory_identity(path: Path) -> tuple[tuple[object, ...], ...] | None:
    if not path.exists():
        return None
    identity: list[tuple[object, ...]] = []
    for candidate in sorted(path.rglob("*")):
        stat = candidate.lstat()
        identity.append(
            (
                candidate.relative_to(path).as_posix(),
                stat.st_mode,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_size,
                stat.st_ino,
            )
        )
    return tuple(identity)


def _destination_key(path: Path) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in path.parts)


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _projection_references(
    document: str,
) -> tuple[dict[str, ValueReference], dict[str, ValueReference]]:
    parser = TemplateParser()
    parser.feed(document)
    return (
        {reference.source: reference for reference in parser.value_references},
        {reference.source: reference for reference in parser.output_references},
    )


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
        f"Run `marimo-studio check {resolved.workspace.notebook} "
        f"--view {view_name}` for repair details."
    )


def _runtime_config(
    adapters: ExportAdapters,
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    view_name: str,
    document: str,
    notebook_source: str,
) -> tuple[str, dict[str, object]]:
    value_references, output_references = _projection_references(document)
    projection = adapters.browser.project(
        studio.notebook,
        notebook_source,
        values=value_references,
        outputs=output_references,
    )
    view = resolved.views[view_name]
    cell_bindings = resolved.runtime_cell_bindings(
        None,
        required_aliases=view.cell_aliases,
    )
    value_bindings = view.runtime_value_bindings(None)
    output_bindings = view.runtime_output_bindings(None)
    controls = resolved.runtime_control_cells(None)
    revision = _digest(
        view_name,
        document,
        projection.code,
        json.dumps(cell_bindings, sort_keys=True),
        json.dumps(value_bindings, sort_keys=True),
        json.dumps(output_bindings, sort_keys=True),
    )
    support_url = f"./{SUPPORT_ROOT.as_posix()}/views/{view_name}"
    marimo_config = adapters.runtime_config(studio.notebook)
    config: dict[str, object] = {
        "schema": 1,
        "revision": revision,
        "view": view_name,
        "views": [view_name],
        "runtime": {
            "id": RUNTIME_ID,
            "instance": projection.instance,
            "available": [RUNTIME_ID],
            "data": projection.runtime_data(),
            "controls": {"cells": controls},
        },
        "rootUrl": "./",
        "publicRootUrl": "./",
        "documentRootUrl": "./",
        "supportUrl": support_url,
        "cellBindings": cell_bindings,
        "valueBindings": value_bindings,
        "outputBindings": output_bindings,
        "diagnostics": [],
        "appConfig": resolved.notebook.app_config,
        "userConfig": marimo_config.user,
        "configOverrides": marimo_config.overrides,
        "dev": False,
        "mode": "run",
    }
    rendered = runtime_document(
        document,
        root_url="./",
        support_url=support_url,
        assets_url=f"./{SUPPORT_ROOT.as_posix()}/assets",
        dev=False,
        revision=revision,
        runtime=RUNTIME_ID,
        filename="notebook.py",
        marimo_version=projection.version,
    )
    return rendered, config


def _asset_files(
    source: Path,
    destination: Path,
    owner: str,
    *,
    skip: frozenset[str] = frozenset(),
) -> list[_AssetCopy]:
    if source.is_symlink():
        raise StaticExportError(f"Static export source is a symlink: {source}")
    assets: list[_AssetCopy] = []

    def collect(directory: Path, relative: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            if not relative.parts and child.name in skip:
                continue
            if child.is_symlink():
                raise StaticExportError(f"Static export source is a symlink: {child}")
            child_relative = relative / child.name
            if child.is_dir():
                collect(child, child_relative)
            elif child.is_file():
                assets.append(
                    _AssetCopy(
                        source=child,
                        destination=destination / child_relative,
                        owner=owner,
                        stamp=_file_stamp(child),
                    )
                )

    collect(source, Path())
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
    resolved: ResolvedStudio,
    view_name: str,
) -> tuple[_AssetCopy, ...]:
    support = SUPPORT_ROOT / "views" / view_name
    generated = [
        (Path("index.html"), "the generated view document"),
        (Path(".nojekyll"), "the generated site marker"),
        (support / "config", "the generated runtime configuration"),
        *(
            (support / "cells" / alias, "a generated cell fragment")
            for alias in resolved.views[view_name].cell_aliases
        ),
    ]
    copies = _asset_files(
        _assets.runtime_assets_path(),
        SUPPORT_ROOT / "assets",
        "the Studio runtime",
    )
    copies.extend(
        _asset_files(
            studio.views[view_name].root,
            Path(),
            f"view {view_name!r}",
            skip=frozenset({"index.html"}),
        )
    )
    public = studio.notebook.parent / "public"
    if public.is_dir():
        copies.extend(
            _asset_files(
                public,
                Path("public"),
                "the notebook public directory",
            )
        )

    for asset in copies:
        if asset.owner == f"view {view_name!r}" and (
            asset.destination.parts
            and unicodedata.normalize("NFC", asset.destination.parts[0]).casefold()
            in RESERVED_VIEW_ASSET_NAMES
        ):
            raise StaticExportError(
                f"View asset path {asset.destination.as_posix()!r} uses a reserved "
                "Marimo or Studio route. Rename the view asset."
            )

    files: dict[tuple[str, ...], tuple[str, Path]] = {}
    directories: dict[tuple[str, ...], tuple[str, Path]] = {}
    for destination, owner in generated:
        _claim_asset(files, directories, destination, owner)
    for asset in copies:
        _claim_asset(files, directories, asset.destination, asset.owner)
    return tuple(copies)


def _write_bundle(
    adapters: ExportAdapters,
    output: Path,
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    view_name: str,
    document: str,
    notebook_source: str,
) -> int:
    rendered, config = _runtime_config(
        adapters,
        studio,
        resolved,
        view_name,
        document,
        notebook_source,
    )
    support = output / SUPPORT_ROOT
    view_support = support / "views" / view_name

    assets = _asset_plan(studio, resolved, view_name)
    for asset in assets:
        if _file_stamp(asset.source) != asset.stamp:
            raise StaticExportError(
                "The static export sources changed while the bundle was prepared. "
                "Run the export again."
            )
        destination = output / asset.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset.source, destination)

    output.joinpath("index.html").write_text(rendered, encoding="utf-8")
    view_support.mkdir(parents=True, exist_ok=True)
    view_support.joinpath("config").write_text(
        json.dumps(config, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    cells = view_support / "cells"
    cells.mkdir(parents=True, exist_ok=True)
    for alias in resolved.views[view_name].cell_aliases:
        cells.joinpath(alias).write_text(render(cell_host(alias)), encoding="utf-8")
    output.joinpath(".nojekyll").touch()
    try:
        stable = (
            assets == _asset_plan(studio, resolved, view_name)
            and document == studio.views[view_name].template.read_text(encoding="utf-8")
            and notebook_source == studio.notebook.read_text(encoding="utf-8")
        )
    except OSError:
        stable = False
    if not stable:
        raise StaticExportError(
            "The static export sources changed while the bundle was written. "
            "Run the export again."
        )
    return sum(1 for path in output.rglob("*") if path.is_file())


def _validate_output(
    output: Path,
    studio: StudioWorkspace,
    view_name: str,
    *,
    force: bool,
) -> _OutputTarget:
    expanded = output.expanduser()
    if expanded.is_symlink():
        raise StaticExportError(f"Output is a symlink: {expanded}")
    resolved = expanded.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise StaticExportError(
            f"Choose a dedicated static export directory: {resolved}"
        )
    protected = [
        studio.notebook,
        studio.views[view_name].root,
        _assets.runtime_assets_path(),
    ]
    public = studio.notebook.parent / "public"
    if public.exists():
        protected.append(public)
    for source in protected:
        source = source.resolve()
        if (
            source == resolved
            or source.is_relative_to(resolved)
            or resolved.is_relative_to(source)
        ):
            raise StaticExportError(
                f"Output overlaps a static export source: {resolved}"
            )
    if resolved.exists() and not resolved.is_dir():
        raise StaticExportError(f"Output must be a directory: {resolved}")
    if resolved.exists() and not force:
        raise StaticExportError(
            f"Output already exists: {resolved}. Pass --force to replace it."
        )
    return _OutputTarget(resolved, _directory_identity(resolved))


def _publish_absent(staged: Path, output: Path) -> None:
    try:
        output.mkdir()
    except FileExistsError as error:
        raise StaticExportError(
            f"Output changed while the static export was prepared: {output}. "
            "Run the export again."
        ) from error
    if os.name == "nt":
        output.rmdir()
    try:
        os.replace(staged, output)
    except OSError:
        if os.name != "nt":
            with suppress(OSError):
                output.rmdir()
        raise


def _preserve_previous(previous: Path, output: Path) -> None:
    recovery = Path(
        tempfile.mkdtemp(
            dir=output.parent,
            prefix=f".{output.name}-recovery-",
        )
    )
    recovery.rmdir()
    os.replace(previous, recovery)
    try:
        _publish_absent(recovery, output)
    except (OSError, StaticExportError) as error:
        raise StaticExportError(
            f"Output changed while the static export was committed: {output}. "
            f"The previous output is preserved at {recovery}."
        ) from error


def _commit_bundle(staged: Path, target: _OutputTarget) -> None:
    output = target.path
    if target.identity is None:
        try:
            _publish_absent(staged, output)
        except StaticExportError:
            raise
        except OSError as error:
            raise StaticExportError(
                f"Could not create static export directory {output}: {error}"
            ) from error
        return

    previous = staged.parent / "previous"
    try:
        os.replace(output, previous)
        if _directory_identity(previous) != target.identity:
            _preserve_previous(previous, output)
            raise StaticExportError(
                f"Output changed while the static export was prepared: {output}. "
                "Run the export again."
            )
        try:
            _publish_absent(staged, output)
        except Exception:
            _preserve_previous(previous, output)
            raise
    except OSError as error:
        raise StaticExportError(
            f"Could not replace static export directory {output}: {error}"
        ) from error
    shutil.rmtree(previous, ignore_errors=True)


def export_view(
    target: str | Path,
    output: str | Path,
    *,
    view: str | None = None,
    force: bool = False,
) -> StaticExportResult:
    """Export one configured view as an HTTP-hosted WebAssembly site."""
    adapters = create_export_adapters()
    studio = load_studio(target)
    selected = view or studio.default_view
    if selected not in studio.views:
        available = ", ".join(studio.views)
        raise StaticExportError(
            f"Unknown view {selected!r}. Available views: {available}."
        )

    document = studio.views[selected].template.read_text(encoding="utf-8")
    notebook_source = studio.notebook.read_text(encoding="utf-8")
    resolved = resolve_studio(
        studio,
        view_name=selected,
        view_documents={selected: document},
    )
    _projection_error(resolved, selected)
    output_target = _validate_output(
        Path(output),
        studio,
        selected,
        force=force,
    )
    destination = output_target.path
    destination.parent.mkdir(parents=True, exist_ok=True)

    staging_root = Path(
        tempfile.mkdtemp(
            dir=destination.parent,
            prefix=f".{destination.name}-export-",
        )
    )
    staged = staging_root / "bundle"
    staged.mkdir()
    try:
        files = _write_bundle(
            adapters,
            staged,
            studio,
            resolved,
            selected,
            document,
            notebook_source,
        )
        _commit_bundle(staged, output_target)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return StaticExportResult(
        notebook=studio.notebook,
        view=selected,
        output=destination,
        files=files,
    )


__all__ = ["StaticExportResult", "export_view"]
