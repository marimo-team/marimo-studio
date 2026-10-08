"""Resolve view sites against the saved notebook graph."""

from __future__ import annotations

from collections.abc import Mapping

from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio._projections.studio import resolve_studio as _resolve_studio
from marimo_studio._views.inspection import inspect_view_sites
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.view_providers._artifact_sites import ArtifactSite


def resolve_studio(
    studio: StudioWorkspace,
    *,
    include_code: bool = False,
    notebook_source: str | None = None,
    view_name: str | None = None,
    published_sites: Mapping[str, tuple[ArtifactSite, ...]] | None = None,
) -> ResolvedStudio:
    """Resolve configured projections through view-owned inspection."""
    return _resolve_studio(
        studio,
        inspect_notebook=inspect_notebook,
        inspect_sites=inspect_view_sites,
        include_code=include_code,
        notebook_source=notebook_source,
        view_name=view_name,
        published_sites=published_sites,
    )
