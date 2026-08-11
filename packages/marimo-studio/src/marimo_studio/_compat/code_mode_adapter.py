"""Expose Marimo code-mode state through a Studio-owned capability."""

from __future__ import annotations

from starlette.types import Scope

from marimo_studio._agent_transport import StudioServerConnection
from marimo_studio._compat.code_mode import (
    attach_code_mode_session,
    code_mode_connection,
)


class PrivateCodeModeBridge:
    """Adapt code-mode request state for the tested Marimo layout."""

    def attach_session(self, scope: Scope) -> Scope:
        return attach_code_mode_session(scope)

    def connection(self) -> StudioServerConnection:
        return code_mode_connection()


__all__ = ["PrivateCodeModeBridge"]
