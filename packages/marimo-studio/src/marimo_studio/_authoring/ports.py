"""Handle contracts shared by authoring interfaces."""

from pathlib import Path
from typing import Protocol

from marimo_studio._browser_client.transport import StudioServerConnection


class WorkspaceHandle(Protocol):
    @property
    def notebook(self) -> Path: ...

    def _connection(self) -> StudioServerConnection | None: ...
