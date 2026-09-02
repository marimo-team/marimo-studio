"""Internal artifact, adapter, lifecycle, and coordination failures."""

from __future__ import annotations

from marimo_studio.errors import ConfigurationError, MarimoStudioError, ProtocolError


class ArtifactIntegrityError(ConfigurationError):
    """Published artifact bytes do not match their immutable identity."""

    code = "artifact-integrity-failed"


class CompatibilityError(ProtocolError):
    """The pinned Marimo release cannot provide a required integration capability."""

    code = "marimo-integration-incompatible"


class RuntimeStartupError(MarimoStudioError):
    """The selected Marimo kernel stopped during Studio startup."""

    code = "runtime-startup-failed"


class RuntimeSyncError(MarimoStudioError):
    """The browser session and inspected notebook have not synchronized."""

    code = "runtime-sync-pending"
    status_code = 409
    transient = True


class ViewDeletionInProgress(MarimoStudioError):
    """A view-scoped operation was superseded by deletion."""

    code = "view-deletion-in-progress"
    status_code = 409
    transient = True

    def __init__(self, view_name: str) -> None:
        super().__init__(f"View {view_name!r} is being deleted.")
        self.view_name = view_name

    def diagnostic_details(self) -> dict[str, object]:
        return {"view": self.view_name}


class ViewDeletionCapacityError(MarimoStudioError):
    """The server has no free dedicated view-deletion worker."""

    code = "view-deletion-capacity-exhausted"
    status_code = 503
    transient = True
    public_hint = "Retry after an in-flight view deletion finishes."

    def __init__(self) -> None:
        super().__init__(
            "Studio is already processing the maximum number of view deletions."
        )


class WorkspaceInitializationError(MarimoStudioError):
    """A Studio definition needs its first authored view."""

    code = "workspace-not-initialized"
    status_code = 409
    public_hint = "Open the notebook in edit mode and create its first view."

    def __init__(self, default_view: str) -> None:
        super().__init__(
            f"Studio is configured and needs its first view {default_view!r}."
        )
        self.default_view = default_view

    def diagnostic_details(self) -> dict[str, object]:
        return {
            "state": "needs-view",
            "default_view": self.default_view,
            "views": [],
        }
