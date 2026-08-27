"""Give expected Studio failures one meaning across every user surface.

Configuration, source, provider, artifact, protocol, runtime, session, and
workspace failures use the same codes and recovery details in the CLI, HTTP
responses, and agent results. These error types also carry CLI exit codes, HTTP
status, whether retrying may succeed, repair hints, and structured details such
as paths, revisions, and available choices.

Callers can render a human explanation and a machine-readable result from the
same failure. Error types may override ``public_message`` when browser text
must differ from diagnostic detail.
"""

from __future__ import annotations

from collections.abc import Mapping
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


class ViewProjectError(ConfigurationError):
    """A provider project or artifact violates the view contract."""

    code = "view-project-error"
    public_hint = "Fix the provider diagnostic, then build the view again."

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

    def with_source(self, source: Path | str) -> ViewProjectError:
        if self.source is not None:
            return self
        return ViewProjectError(
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
    """A Studio protocol record or installed Marimo runtime is incompatible."""

    code = "protocol-error"
    exit_code = 6


class CapabilityInputError(MarimoStudioError):
    """A capability request contains an invalid field or value."""

    exit_code = 2
    status_code = 400

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field

    def diagnostic_details(self) -> dict[str, object]:
        return {"field": self.field}


class RuntimeTimeoutError(MarimoStudioError):
    """Notebook execution did not settle within its analysis budget."""

    code = "runtime-timeout"
    status_code = 504
    public_hint = (
        "Increase runtime_timeout for expected setup work, or fix the notebook "
        "operation that did not finish. The CLI option is --runtime-timeout."
    )


class AgentRequestError(MarimoStudioError):
    """An agent-facing server request failed with a structured error code."""

    exit_code = 5

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 500,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = dict(details or {})

    def diagnostic_details(self) -> dict[str, object]:
        return self.details.copy()


class DependencyError(ConfigurationError):
    """The notebook environment could not be prepared."""

    code = "dependency-error"
    exit_code = 7


class StaticExportError(ConfigurationError):
    """A static view bundle could not be created."""

    code = "static-export-error"


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


class SourceValidationError(MarimoStudioError):
    """Authored source content violates its document contract."""

    code = "invalid-source-content"
    status_code = 400


class SourceTooLargeError(MarimoStudioError):
    """An authored source document exceeds the supported file boundary."""

    code = "source-too-large"
    status_code = 413


class SourceConflictError(MarimoStudioError):
    """An authored view file changed after the browser loaded it."""

    code = "source-conflict"
    status_code = 412

    def __init__(
        self,
        name: str,
        revision: str | None,
        *,
        external_recovery: str | None = None,
    ) -> None:
        super().__init__(f"{name} changed on disk.")
        self.revision = revision
        self.external_recovery = external_recovery

    def diagnostic_details(self) -> dict[str, object]:
        details: dict[str, object] = {}
        if self.revision is not None:
            details["revision"] = self.revision
        if self.external_recovery is not None:
            details["external_recovery"] = self.external_recovery
        return details


class ViewNotFoundError(MarimoStudioError):
    """A requested Studio view does not exist."""

    code = "view-not-found"
    status_code = 404

    def __init__(self, name: str, *, available: tuple[str, ...] = ()) -> None:
        choices = f" Available views: {', '.join(available)}." if available else ""
        super().__init__(f"View {name!r} does not exist.{choices}")
        self.name = name
        self.available = available

    def diagnostic_details(self) -> dict[str, object]:
        return {"view": self.name, "available_views": list(self.available)}


class ProviderNotFoundError(ConfigurationError):
    """A requested view provider is not installed."""

    code = "provider-not-found"
    status_code = 404

    def __init__(self, key: str, *, available: tuple[str, ...] = ()) -> None:
        choices = f" Installed providers: {', '.join(available)}." if available else ""
        super().__init__(f"View provider {key!r} is not installed.{choices}")
        self.key = key
        self.available = available

    def diagnostic_details(self) -> dict[str, object]:
        return {"provider": self.key, "available_providers": list(self.available)}


class ViewExistsError(MarimoStudioError):
    """A requested Studio view name already identifies a project."""

    code = "view-exists"
    status_code = 409

    def __init__(self, name: str, *, missing_manifest: bool = False) -> None:
        message = (
            f"A view directory named {name!r} exists without required view.toml."
            if missing_manifest
            else f"A view named {name!r} already exists."
        )
        super().__init__(message)
        self.name = name

    def diagnostic_details(self) -> dict[str, object]:
        return {"view": self.name}


class LastViewError(MarimoStudioError):
    """A notebook must retain one Studio view."""

    code = "last-view"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Keep at least one view.")


__all__ = [
    "AgentRequestError",
    "BindingError",
    "CapabilityInputError",
    "ConfigurationError",
    "DependencyError",
    "LastViewError",
    "MarimoStudioError",
    "NotebookSourceError",
    "ProtocolError",
    "ProviderNotFoundError",
    "RuntimeSelectionError",
    "RuntimeTimeoutError",
    "SourceConflictError",
    "SourceEncodingError",
    "SourceNotFoundError",
    "SourceTooLargeError",
    "SourceValidationError",
    "StaticExportError",
    "ViewExistsError",
    "ViewNotFoundError",
    "ViewProjectError",
]
