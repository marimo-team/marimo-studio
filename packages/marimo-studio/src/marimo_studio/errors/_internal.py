"""Internal artifact, adapter, lifecycle, and coordination failures."""

from __future__ import annotations

from pathlib import Path

from marimo_studio.errors import ConfigurationError, MarimoStudioError, ProtocolError


class ArtifactCompatibilityError(ConfigurationError):
    """Generated artifact state targets another provider API version."""


class ArtifactIntegrityError(ConfigurationError):
    """Published artifact bytes do not match their immutable identity."""

    code = "artifact-integrity-failed"


class CompatibilityError(ProtocolError):
    """The installed Marimo layout cannot provide a required capability."""

    code = "marimo-layout-incompatible"


class RuntimeStartupError(MarimoStudioError):
    """The selected Marimo kernel stopped during Studio startup."""

    code = "runtime-startup-failed"


class RuntimeSyncError(MarimoStudioError):
    """The browser session and inspected notebook have not synchronized."""

    code = "runtime-sync-pending"
    status_code = 409
    transient = True


class ViewDeletionError(MarimoStudioError):
    """A view removal failed before or during filesystem cleanup."""

    code = "view-deletion-error"

    def __init__(self, cleanup: Path | None = None) -> None:
        self.cleanup = cleanup
        if cleanup is None:
            super().__init__(
                "The view could not be removed. Its project and default view were "
                "restored."
            )
        else:
            super().__init__(
                "The view was removed, but filesystem cleanup is incomplete at "
                f"{cleanup}."
            )

    def diagnostic_details(self) -> dict[str, object]:
        return {"cleanup": str(self.cleanup) if self.cleanup is not None else None}


class ViewInUseError(MarimoStudioError):
    """A view has artifact readers in another process."""

    code = "view-in-use"
    status_code = 409

    def __init__(self, name: str) -> None:
        super().__init__(
            f"View {name!r} is open in another process. Close its readers and retry."
        )


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
