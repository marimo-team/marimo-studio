"""Expected configuration, dependency, protocol, and server failures."""

from __future__ import annotations


class MarimoStudioError(Exception):
    """Base class for expected Studio and runtime failures."""

    code = "marimo-studio-error"
    exit_code = 3


class ConfigurationError(MarimoStudioError):
    """The Studio configuration or notebook is invalid."""

    code = "configuration-error"


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
