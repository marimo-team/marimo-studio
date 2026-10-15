"""Define the public SDK for frontend view providers.

A provider reports availability, offers starters, and inspects a view project
for its Source documents, build inputs, projection sites, and renders.
It then builds the view's page beneath the staging root in its request.
Built-in and installed third-party providers use the same records, and import
every Studio name from this module.

Provider methods are synchronous. ``create()`` receives a saved notebook
snapshot and returns starter files with the cell targets they use.
``inspect()`` describes the project without changing it. Studio assigns each
projection site its ID and adds the site attribute to the build snapshot before
it calls ``build()``. A ``RenderProvider`` also declares renders, writes their
template beneath the template root, and returns files from ``render()``
whenever the notebook results a render reads change. A page shows a render
with ``<marimo-output render="...">``. Raise ``ProviderError`` for a problem
the author can fix in the project.

The helpers cover work that every provider repeats: ``project_files`` and
``copy_inputs`` list and copy build inputs, ``probe_tool`` checks an external
tool, ``html_sites`` finds projection sites in HTML, ``parse_accept`` reads an
output host's ``accept`` attribute, ``render_page`` writes a page that shows
one render, and ``PackagedStarter`` with ``create_starter`` ships starter files
as package data.
``marimo_studio.view_providers.testing.check_provider`` runs a provider
through the same steps as Studio.
"""

from marimo_studio._notebook.records import (
    CellConfigSpec,
    CellKind,
    CellRef,
    CellSpec,
    NotebookSpec,
    SourceSpan,
)
from marimo_studio._processes.operation import (
    ProviderCancellation,
    ProviderCommandError,
    ProviderCommandResult,
    ProviderRunner,
)
from marimo_studio.view_providers._records import (
    BuildInput,
    BuildInputKind,
    BuildProfile,
    BuildRequest,
    BuildResult,
    DocumentAccess,
    InspectionRequest,
    JsonValue,
    ProjectDiagnostic,
    ProjectInspection,
    ProjectionKind,
    ProjectionSite,
    ProviderAvailability,
    ProviderError,
    ProviderInfo,
    ProviderStarter,
    Render,
    RenderCell,
    RenderFile,
    RenderOutput,
    RenderProvider,
    RenderRequest,
    RenderResult,
    RenderValue,
    Representation,
    Size,
    SourceDocument,
    SourceLocation,
    StarterCellTarget,
    StarterContext,
    StarterPlan,
    ViewProject,
    ViewProvider,
)
from marimo_studio.view_providers._sites import html_sites
from marimo_studio.view_providers._starters import (
    PackagedStarter,
    StarterMarkers,
    create_starter,
    script_json,
)
from marimo_studio.view_providers._toolkit import (
    copy_inputs,
    probe_tool,
    project_files,
    project_path,
    render_page,
)
from marimo_studio.view_providers._validation import parse_accept

__all__ = [
    "BuildInput",
    "BuildInputKind",
    "BuildProfile",
    "BuildRequest",
    "BuildResult",
    "CellConfigSpec",
    "CellKind",
    "CellRef",
    "CellSpec",
    "DocumentAccess",
    "InspectionRequest",
    "JsonValue",
    "NotebookSpec",
    "PackagedStarter",
    "ProjectDiagnostic",
    "ProjectInspection",
    "ProjectionKind",
    "ProjectionSite",
    "ProviderAvailability",
    "ProviderCancellation",
    "ProviderCommandError",
    "ProviderCommandResult",
    "ProviderError",
    "ProviderInfo",
    "ProviderRunner",
    "ProviderStarter",
    "Render",
    "RenderCell",
    "RenderFile",
    "RenderOutput",
    "RenderProvider",
    "RenderRequest",
    "RenderResult",
    "RenderValue",
    "Representation",
    "Size",
    "SourceDocument",
    "SourceLocation",
    "SourceSpan",
    "StarterCellTarget",
    "StarterContext",
    "StarterMarkers",
    "StarterPlan",
    "ViewProject",
    "ViewProvider",
    "copy_inputs",
    "create_starter",
    "html_sites",
    "parse_accept",
    "probe_tool",
    "project_files",
    "project_path",
    "render_page",
    "script_json",
]
