"""Expose Marimo code-mode state through a Studio-owned capability."""

from __future__ import annotations

from pathlib import Path

from starlette.types import Scope

from marimo_studio._compat.code_mode import (
    active_notebook,
    attach_code_mode_session,
    code_mode_connection,
)
from marimo_studio.agent._transport import StudioServerConnection


class PrivateCodeModeBridge:
    """Adapt code-mode request state for the tested Marimo layout."""

    def attach_session(self, scope: Scope, notebook: Path) -> Scope:
        return attach_code_mode_session(scope, notebook)

    def active_notebook(self) -> Path:
        return active_notebook()

    def connection(self) -> StudioServerConnection:
        return code_mode_connection()
