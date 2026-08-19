"""Inspect Studio workspace state before authoring a view."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    discover_views,
)
from marimo_studio.errors import ConfigurationError

OverviewState = Literal["unconfigured", "needs-view", "ready"]


@dataclass(frozen=True)
class ViewOverview:
    """Identify one authored view in a Studio workspace."""

    name: str
    path: Path
    default: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "default": self.default,
        }


@dataclass(frozen=True)
class StudioOverview:
    """Describe configuration and views for one saved notebook."""

    notebook: Path
    state: OverviewState
    config_path: Path | None
    config_source: Literal["notebook", "pyproject"] | None
    view_root: Path
    default_view: str | None
    default_runtime: str | None
    runtimes: tuple[str, ...]
    bindings: dict[str, str]
    views: tuple[ViewOverview, ...]

    @property
    def configured(self) -> bool:
        return self.state != "unconfigured"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "state": self.state,
            "configured": self.configured,
            "config": str(self.config_path) if self.config_path is not None else None,
            "config_source": self.config_source,
            "view_root": str(self.view_root),
            "default_view": self.default_view,
            "default_runtime": self.default_runtime,
            "runtimes": list(self.runtimes),
            "bindings": self.bindings,
            "views": [view.to_dict() for view in self.views],
        }


def overview(notebook: str | Path) -> StudioOverview:
    """Return Studio configuration and view state for a saved notebook."""
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")

    definition = discover_studio_definition(notebook_path)
    if definition is None:
        return StudioOverview(
            notebook=notebook_path,
            state="unconfigured",
            config_path=None,
            config_source=None,
            view_root=canonical_view_root(notebook_path),
            default_view=None,
            default_runtime=None,
            runtimes=(),
            bindings={},
            views=(),
        )

    discovered = discover_views(definition.view_root)
    if discovered and definition.default_view not in discovered:
        raise ConfigurationError(
            f"Default view {definition.default_view!r} does not exist in "
            f"{definition.view_root}"
        )
    views = tuple(
        ViewOverview(
            name=name,
            path=view.root,
            default=name == definition.default_view,
        )
        for name, view in discovered.items()
    )
    return StudioOverview(
        notebook=notebook_path,
        state="ready" if views else "needs-view",
        config_path=definition.config_path,
        config_source=definition.config_source,
        view_root=definition.view_root,
        default_view=definition.default_view,
        default_runtime=definition.default_runtime,
        runtimes=definition.runtimes,
        bindings={name: str(ref) for name, ref in definition.cells.items()},
        views=views,
    )


__all__ = ["OverviewState", "StudioOverview", "ViewOverview", "overview"]
