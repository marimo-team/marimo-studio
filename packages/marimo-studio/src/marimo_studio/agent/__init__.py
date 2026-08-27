"""Author and validate Studio views from notebook-bound agent code.

Open the active notebook in each code-mode execution:

    import marimo_studio.agent as studio

    workspace = studio.open()
    view = await workspace.create_view("dashboard")
    inspection = await view.inspect()
"""

from marimo_studio._authoring.view_api import View as View
from marimo_studio._authoring.workspace import ProviderReport as ProviderReport
from marimo_studio._authoring.workspace_api import Workspace as Workspace
from marimo_studio._authoring.workspace_api import doctor as doctor
from marimo_studio._authoring.workspace_api import open_workspace as open
from marimo_studio._browser_client.records import (
    ViewActivationResult as ViewActivationResult,
)
from marimo_studio._delivery.export import StaticExportResult as StaticExportResult
from marimo_studio._notebook.records import CellSelector as CellSelector
from marimo_studio._notebook.records import InspectionResult as InspectionResult
from marimo_studio._validation.evidence import AnalysisAction as AnalysisAction
from marimo_studio._validation.records import ValidationLevel as ValidationLevel
from marimo_studio._validation.records import ValidationReport as ValidationReport
from marimo_studio._views.api import ViewRemovalResult as ViewRemovalResult
from marimo_studio._views.records import Publication as Publication
from marimo_studio._views.records import Starter as Starter
from marimo_studio._views.records import StudioDiagnostic as StudioDiagnostic
from marimo_studio._views.records import StudioOverview as StudioOverview
from marimo_studio._views.records import ViewDocument as ViewDocument
from marimo_studio._views.records import ViewFreshness as ViewFreshness
from marimo_studio._views.records import ViewInspection as ViewInspection
from marimo_studio._views.records import ViewOverview as ViewOverview
from marimo_studio._workspace.models import BindingResult as BindingResult

__all__ = [
    "AnalysisAction",
    "BindingResult",
    "CellSelector",
    "InspectionResult",
    "ProviderReport",
    "Publication",
    "Starter",
    "StaticExportResult",
    "StudioDiagnostic",
    "StudioOverview",
    "ValidationLevel",
    "ValidationReport",
    "View",
    "ViewActivationResult",
    "ViewDocument",
    "ViewFreshness",
    "ViewInspection",
    "ViewOverview",
    "ViewRemovalResult",
    "Workspace",
    "doctor",
    "open",
]
