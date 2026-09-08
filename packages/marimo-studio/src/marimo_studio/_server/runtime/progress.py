"""Describe observable work while a runtime projection is prepared."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeProgress:
    message: str
    completed: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        if not self.message or len(self.message) > 2048:
            raise ValueError(
                "Runtime progress requires a message of up to 2048 characters"
            )
        if self.completed is None and self.total is None:
            return
        if (
            type(self.completed) is not int
            or type(self.total) is not int
            or not 0 < self.total <= 2**53 - 1
            or not 0 <= self.completed <= self.total
        ):
            raise ValueError(
                "Runtime progress requires 0 <= completed <= total and total > 0"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "message": self.message,
            **(
                {"completed": self.completed, "total": self.total}
                if self.completed is not None
                else {}
            ),
        }


RuntimeProgressSink = Callable[[RuntimeProgress], None]
