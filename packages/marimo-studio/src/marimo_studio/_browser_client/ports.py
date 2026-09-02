"""Code-mode ports consumed by browser client services."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from starlette.types import Scope

from marimo_studio._browser_client.transport import StudioServerConnection


class CodeModeBridge(Protocol):
    def attach_session(self, scope: Scope, notebook: Path) -> Scope: ...

    def active_notebook(self) -> Path: ...

    def connection(self) -> StudioServerConnection: ...
