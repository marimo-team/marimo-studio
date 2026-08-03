"""Validate the installed Marimo version at compatibility boundaries."""

import marimo
from packaging.version import InvalidVersion, Version

from marimo_studio.errors import ProtocolError

_MINIMUM_MARIMO_VERSION = Version("0.23.16")


def assert_supported_version() -> None:
    """Require Marimo 0.23.16 or newer."""
    try:
        installed = Version(marimo.__version__)
    except InvalidVersion as error:
        raise ProtocolError(
            f"Cannot parse installed marimo version {marimo.__version__!r}."
        ) from error
    if installed < _MINIMUM_MARIMO_VERSION:
        raise ProtocolError(
            f"marimo {marimo.__version__} is incompatible with this runtime. "
            "Install marimo>=0.23.16."
        )


__all__ = ["assert_supported_version"]
