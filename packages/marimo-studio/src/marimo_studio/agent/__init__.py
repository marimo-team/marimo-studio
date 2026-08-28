"""Author and verify the current Marimo Studio workspace."""

from marimo_studio._authoring.current_api import View as View
from marimo_studio._authoring.current_api import Workspace as Workspace
from marimo_studio._authoring.current_api import (
    current_workspace as current_workspace,
)
from marimo_studio._browser_client.records import ShowResult as ShowResult
from marimo_studio._validation.evidence import ValidationIssue as ValidationIssue
from marimo_studio._validation.records import ValidationReport as ValidationReport

__all__ = [
    "ShowResult",
    "ValidationIssue",
    "ValidationReport",
    "View",
    "Workspace",
    "current_workspace",
]
