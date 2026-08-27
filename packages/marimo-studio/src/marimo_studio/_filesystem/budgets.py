"""Bound provider inputs and published browser file trees."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from marimo_studio.errors import ConfigurationError


@dataclass(frozen=True)
class FileBudget:
    max_files: int
    max_file_bytes: int
    max_total_bytes: int


@dataclass
class FileBudgetTracker:
    budget: FileBudget
    label: str
    files: int = 0
    total_bytes: int = 0

    def require_count(self, files: int) -> None:
        if files > self.budget.max_files:
            raise ConfigurationError(
                f"{self.label} contains {files} files. The limit is "
                f"{self.budget.max_files}. Remove files or split the project."
            )

    def add(self, path: str, size: int) -> None:
        self.files += 1
        self.require_count(self.files)
        if size > self.budget.max_file_bytes:
            raise ConfigurationError(
                f"{self.label} file {path!r} is {size} bytes. The per-file limit "
                f"is {self.budget.max_file_bytes} bytes. Reduce the file size."
            )
        self.total_bytes += size
        if self.total_bytes > self.budget.max_total_bytes:
            raise ConfigurationError(
                f"{self.label} is more than {self.budget.max_total_bytes} bytes. "
                "Remove files or reduce their sizes."
            )


PROJECT_INPUT_BUDGET = FileBudget(
    max_files=4_096,
    max_file_bytes=64 * 1024 * 1024,
    max_total_bytes=512 * 1024 * 1024,
)
ARTIFACT_OUTPUT_BUDGET = FileBudget(
    max_files=4_096,
    max_file_bytes=128 * 1024 * 1024,
    max_total_bytes=1024 * 1024 * 1024,
)


def enforce_file_budget(
    files: Sequence[tuple[str, int]],
    budget: FileBudget,
    label: str,
) -> None:
    """Reject a file inventory that exceeds its count or byte budget."""
    tracker = FileBudgetTracker(budget, label)
    for path, size in files:
        tracker.add(path, size)
