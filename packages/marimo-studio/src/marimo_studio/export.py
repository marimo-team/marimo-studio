"""Export one custom view as a static WebAssembly site."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from marimo_studio import _assets
from marimo_studio._compat.browser_notebook import browser_notebook_source
from marimo_studio._compat.static_export import static_runtime_config
from marimo_studio._html import cell_host, render, runtime_document
from marimo_studio._workspace.config import load_studio
from marimo_studio._workspace.models import ResolvedStudio, StudioConfig
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


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _value_references(document: str) -> dict[str, ValueReference]:
    parser = TemplateParser()
    parser.feed(document)
    return {reference.source: reference for reference in parser.value_references}


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
        f"Run `marimo-studio check {resolved.studio.notebook} "
        f"--view {view_name}` for repair details."
    )


def _runtime_config(
    studio: StudioConfig,
    resolved: ResolvedStudio,
    view_name: str,
    document: str,
    notebook_source: str,
) -> tuple[str, dict[str, object]]:
    references = _value_references(document)
    code = browser_notebook_source(studio.notebook, notebook_source, references)
    version = _assets.runtime_marimo_version()
    view = resolved.views[view_name]
    cell_bindings = resolved.runtime_cell_bindings(
        None,
        required_aliases=view.cell_aliases,
    )
    value_bindings = view.runtime_value_bindings(None)
    controls = resolved.runtime_control_cells(None)
    revision = _digest(
        view_name,
        document,
        code,
        json.dumps(cell_bindings, sort_keys=True),
        json.dumps(value_bindings, sort_keys=True),
    )
    support_url = f"./{SUPPORT_ROOT.as_posix()}/views/{view_name}"
    marimo_config = static_runtime_config(studio.notebook)
    config: dict[str, object] = {
        "schema": 1,
        "revision": revision,
        "view": view_name,
        "views": [view_name],
        "runtime": {
            "id": RUNTIME_ID,
            "instance": _digest(version, code),
            "available": [RUNTIME_ID],
            "data": {
                "code": code,
                "filename": "notebook.py",
                "version": version,
            },
            "controls": {"cells": controls},
        },
        "rootUrl": "./",
        "supportUrl": support_url,
        "cellBindings": cell_bindings,
        "valueBindings": value_bindings,
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
    )
    return rendered, config


def _copy_tree(source: Path, target: Path) -> None:
    if source.is_symlink():
        raise StaticExportError(f"Static export source is a symlink: {source}")
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.is_symlink():
            raise StaticExportError(f"Static export source is a symlink: {child}")
        destination = target / child.name
        if child.is_dir():
            _copy_tree(child, destination)
        elif child.is_file():
            shutil.copy2(child, destination)


def _write_bundle(
    output: Path,
    studio: StudioConfig,
    resolved: ResolvedStudio,
    view_name: str,
    document: str,
    notebook_source: str,
) -> int:
    rendered, config = _runtime_config(
        studio,
        resolved,
        view_name,
        document,
        notebook_source,
    )
    support = output / SUPPORT_ROOT
    view_support = support / "views" / view_name

    _copy_tree(_assets.runtime_assets_path(), support / "assets")
    _copy_tree(studio.views[view_name].root, view_support / "static")
    view_support.joinpath("static/theme.css").touch(exist_ok=True)
    public = studio.notebook.parent / "public"
    if public.is_dir():
        _copy_tree(public, output / "public")

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
    return sum(1 for path in output.rglob("*") if path.is_file())


def _validate_output(
    output: Path,
    studio: StudioConfig,
    view_name: str,
    *,
    force: bool,
) -> Path:
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
    return resolved


def _commit_bundle(staged: Path, output: Path) -> None:
    previous = staged.parent / "previous"
    moved_previous = False
    try:
        if output.exists():
            os.replace(output, previous)
            moved_previous = True
        try:
            os.replace(staged, output)
        except Exception:
            if moved_previous:
                os.replace(previous, output)
            raise
    except OSError as error:
        raise StaticExportError(
            f"Could not replace static export directory {output}: {error}"
        ) from error
    if moved_previous:
        shutil.rmtree(previous, ignore_errors=True)


def export_view(
    target: str | Path,
    output: str | Path,
    *,
    view: str | None = None,
    force: bool = False,
) -> StaticExportResult:
    """Export one configured view as an HTTP-hosted WebAssembly site."""
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
    destination = _validate_output(
        Path(output),
        studio,
        selected,
        force=force,
    )
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
            staged,
            studio,
            resolved,
            selected,
            document,
            notebook_source,
        )
        _commit_bundle(staged, destination)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return StaticExportResult(
        notebook=studio.notebook,
        view=selected,
        output=destination,
        files=files,
    )


__all__ = ["StaticExportResult", "export_view"]
