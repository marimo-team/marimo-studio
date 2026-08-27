"""Handle contracts shared by authoring interfaces."""

from pathlib import Path
from typing import Protocol

from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._validation.records import ValidationLevel, ValidationReport


class WorkspaceHandle(Protocol):
    @property
    def notebook(self) -> Path: ...

    def _connection(self) -> StudioServerConnection | None: ...

    async def validate(
        self,
        *,
        level: ValidationLevel = "static",
        view: str | None = None,
        browser_timeout: float = 10.0,
        runtime_timeout: float = 60.0,
    ) -> ValidationReport: ...
