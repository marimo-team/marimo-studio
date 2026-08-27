"""Resolve view mounts against the saved notebook graph."""

from __future__ import annotations

from collections.abc import Mapping

from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio._projections.studio import resolve_studio as _resolve_studio
from marimo_studio._views.inspection import inspect_view_mounts
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.view_providers import MountDeclaration


def resolve_studio(
    studio: StudioWorkspace,
    *,
    include_code: bool = False,
    view_name: str | None = None,
    published_mounts: Mapping[str, tuple[MountDeclaration, ...]] | None = None,
) -> ResolvedStudio:
    """Resolve configured projections through view-owned inspection."""
    return _resolve_studio(
        studio,
        inspect_notebook=inspect_notebook,
        inspect_mounts=inspect_view_mounts,
        include_code=include_code,
        view_name=view_name,
        published_mounts=published_mounts,
    )
