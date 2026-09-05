"""Validate Studio-owned constraints around an export destination."""

from __future__ import annotations

from pathlib import Path

import marimo_studio._delivery.assets as _assets
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import StaticExportError


def validate_output(
    output: Path,
    studio: StudioWorkspace,
    *,
    protected_sources: tuple[Path, ...] = (),
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
        studio.view_root,
        studio.notebook.parent / "public",
        *(project.root for project in studio.views.values()),
        _assets.runtime_assets_path(),
        *protected_sources,
    ]
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
    return resolved


def ensure_output_parent(output: Path) -> None:
    """Create missing parents before marimo-export owns the destination."""
    existing = output.parent
    while not existing.exists():
        existing = existing.parent
    try:
        if existing != output.parent:
            with secure_directory(existing) as ancestor:
                ancestor.ensure_directory(output.parent)
    except OSError as error:
        raise_process_cleanup(error)
        raise StaticExportError(
            f"Could not secure static export parent {output.parent}: {error}"
        ) from error


__all__ = ["ensure_output_parent", "validate_output"]
