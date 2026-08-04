"""Expected configuration, dependency, protocol, and server failures."""

from __future__ import annotations

from pathlib import Path


class MarimoStudioError(Exception):
    """Base class for expected Studio and runtime failures."""

    code = "marimo-studio-error"
    exit_code = 3
    status_code = 500
    transient = False
    public_hint = ""

    def public_message(self) -> str:
        """Return the error text safe to expose through browser routes."""
        return str(self)

    def diagnostic_details(self) -> dict[str, object]:
        """Return structured repair context for CLI diagnostics."""
        return {}


class ConfigurationError(MarimoStudioError):
    """The Studio configuration or notebook is invalid."""

    code = "configuration-error"


class NotebookSourceError(ConfigurationError):
    """Marimo cannot compile the current notebook source."""

    code = "notebook-source-error"
    public_hint = "Fix the highlighted cell in Marimo, then save it again."

    def public_message(self) -> str:
        return "Marimo cannot inspect the notebook while a cell contains invalid code."


class TemplateError(ConfigurationError):
    """A view template does not satisfy the presentation contract."""

    code = "template-error"
    public_hint = "Fix the view template, then save it again."

    def __init__(
        self,
        message: str,
        *,
        source: Path | str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.line = line
        self.column = column

    def with_source(self, source: Path | str) -> TemplateError:
        if self.source is not None:
            return self
        return TemplateError(
            f"{source}: {self}",
            source=source,
            line=self.line,
            column=self.column,
        )

    def diagnostic_details(self) -> dict[str, object]:
        if self.source is None:
            return {}
        source: dict[str, object] = {"path": str(self.source)}
        if self.line is not None:
            source["line"] = self.line
        if self.column is not None:
            source["column"] = self.column
        return {"source": source}


class BindingError(ConfigurationError):
    """A semantic cell binding cannot be resolved."""

    code = "binding-error"
    exit_code = 4


class ProtocolError(ConfigurationError):
    """The installed marimo runtime is incompatible."""

    code = "protocol-error"
    exit_code = 6


class DependencyError(ConfigurationError):
    """The notebook environment could not be prepared."""

    code = "dependency-error"
    exit_code = 7


class RuntimeSyncError(MarimoStudioError):
    """The browser session and inspected notebook have not synchronized."""

    code = "runtime-sync-pending"
    status_code = 409
    transient = True


class RuntimeSelectionError(MarimoStudioError):
    """A requested presentation runtime is unavailable."""

    code = "runtime-unavailable"
    status_code = 400


class SourceNotFoundError(MarimoStudioError):
    """A requested authored view file is unavailable."""

    code = "source-not-found"
    status_code = 404


class SourceEncodingError(MarimoStudioError):
    """An authored view file is not valid UTF-8 text."""

    code = "invalid-source-encoding"
    status_code = 400


class SourceConflictError(MarimoStudioError):
    """An authored view file changed after the browser loaded it."""

    code = "source-conflict"
    status_code = 412

    def __init__(self, name: str, revision: str) -> None:
        super().__init__(f"{name} changed on disk.")
        self.revision = revision

    def diagnostic_details(self) -> dict[str, object]:
        return {"revision": self.revision}


class ViewNotFoundError(MarimoStudioError):
    """A requested Studio view does not exist."""

    code = "view-not-found"
    status_code = 404

    def __init__(self, name: str) -> None:
        super().__init__(f"View {name!r} does not exist.")


class LastViewError(MarimoStudioError):
    """A notebook must retain one Studio view."""

    code = "last-view"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Keep at least one view.")


class ViewDeletionError(MarimoStudioError):
    """A removed view's authored files could not be fully deleted."""

    code = "view-deletion-error"

    def __init__(self) -> None:
        super().__init__(
            "The view was removed from Studio, but its files could not be "
            "fully deleted."
        )
