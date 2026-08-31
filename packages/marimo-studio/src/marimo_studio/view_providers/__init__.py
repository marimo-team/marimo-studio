"""Define the public contract for frontend view providers.

A provider reports availability, offers starter projects, describes the files
shown in Source, declares which inputs affect a build, identifies where a page
mounts notebook results, and produces candidate browser files. Bundled and
installed third-party providers use the same request and result records.

Provider methods are synchronous. Creation receives a saved notebook snapshot
and returns starter files with their selected cell targets. Inspection returns
a read-only project description. Building writes browser files beneath the
staging root supplied in its request before returning the entry document and
diagnostics. Studio supplies cancellation and a bounded command runner,
captures immutable inputs, validates provider output, and owns durable
workspace state, publication, sessions, and notebook authorization.
"""

from marimo_studio._notebook.records import (
    CellConfigSpec,
    CellKind,
    CellRef,
    CellSpec,
    NotebookSpec,
    SourceSpan,
)
from marimo_studio.view_providers._mounts import mount_attribute
from marimo_studio.view_providers._operation import (
    ProviderCancellation,
    ProviderCommandResult,
    ProviderRunner,
)
from marimo_studio.view_providers._records import (
    PROVIDER_API_VERSION,
    BuildProfile,
    BuildRequest,
    BuildResult,
    DocumentAccess,
    InspectionRequest,
    JsonValue,
    MountDeclaration,
    ProjectDiagnostic,
    ProjectInput,
    ProjectInputKind,
    ProjectInspection,
    ProjectionKind,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    SourceLocation,
    StarterCellTarget,
    StarterContext,
    StarterPlan,
    ViewProject,
    ViewProvider,
)

__all__ = [
    "PROVIDER_API_VERSION",
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
    "MountDeclaration",
    "NotebookSpec",
    "ProjectDiagnostic",
    "ProjectInput",
    "ProjectInputKind",
    "ProjectInspection",
    "ProjectionKind",
    "ProviderAvailability",
    "ProviderCancellation",
    "ProviderCommandResult",
    "ProviderInfo",
    "ProviderRunner",
    "ProviderStarter",
    "SourceDocument",
    "SourceLocation",
    "SourceSpan",
    "StarterCellTarget",
    "StarterContext",
    "StarterPlan",
    "ViewProject",
    "ViewProvider",
    "mount_attribute",
]
