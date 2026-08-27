"""Browser runtime projection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class BrowserRuntimeCell:
    runtime_id: str
    code: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.runtime_id, "code": self.code}


@dataclass(frozen=True)
class BrowserRuntimeProjection:
    instance: str
    version: str
    commit: str
    code: str
    execution_cells: tuple[BrowserRuntimeCell, ...]
    bootstrap_cell_id: str

    def runtime_data(self) -> dict[str, object]:
        return {
            "code": self.code,
            "filename": "notebook.py",
            "version": self.version,
            "executionCells": [cell.to_dict() for cell in self.execution_cells],
            "bootstrapCellId": self.bootstrap_cell_id,
        }


class BrowserRuntimeProjector(Protocol):
    version: str
    commit: str

    def project(
        self,
        notebook: Path,
        source: str,
    ) -> BrowserRuntimeProjection: ...
