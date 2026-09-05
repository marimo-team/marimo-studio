"""Attach Studio export identity to owned and marimo-export progress."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, TypeAlias

from marimo_export.progress import ProgressEvent

from marimo_studio._delivery.portability import StaticRuntime

StaticExportStepKind: TypeAlias = Literal[
    "build_started",
    "build_finished",
    "bundle_started",
    "bundle_finished",
    "preflight_started",
    "preflight_finished",
    "commit_started",
]
_STEP_KINDS = frozenset(
    {
        "build_started",
        "build_finished",
        "bundle_started",
        "bundle_finished",
        "preflight_started",
        "preflight_finished",
        "commit_started",
    }
)


@dataclass(frozen=True, slots=True)
class StaticExportStep:
    """One Studio-owned build, validation, or commit step."""

    kind: StaticExportStepKind
    completed: int | None = None
    total: int | None = None
    elapsed_seconds: float | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _STEP_KINDS:
            raise ValueError("static export step kind is invalid")
        for name, value in (("completed", self.completed), ("total", self.total)):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(
                    f"static export step {name} must be a nonnegative integer or None"
                )
        if (
            self.completed is not None
            and self.total is not None
            and self.completed > self.total
        ):
            raise ValueError("static export step completed cannot exceed total")
        if self.elapsed_seconds is not None and (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or self.elapsed_seconds < 0
            or not math.isfinite(self.elapsed_seconds)
        ):
            raise ValueError(
                "static export step elapsed_seconds must be nonnegative and finite"
            )
        if self.message is not None and not isinstance(self.message, str):
            raise TypeError("static export step message must be a string or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "completed": self.completed,
            "total": self.total,
            "elapsed_seconds": self.elapsed_seconds,
            "message": self.message,
        }


StaticExportEvent: TypeAlias = ProgressEvent | StaticExportStep


@dataclass(frozen=True, slots=True)
class StaticExportProgress:
    """One Studio export identity wrapped around its owning progress event."""

    view: str
    runtime: StaticRuntime
    event: StaticExportEvent

    def __post_init__(self) -> None:
        if not isinstance(self.view, str) or not self.view:
            raise ValueError("static export progress view must be non-empty")
        if self.runtime not in {"zero-python", "wasm"}:
            raise ValueError("static export progress runtime is invalid")
        if not isinstance(self.event, (ProgressEvent, StaticExportStep)):
            raise TypeError(
                "static export progress event must be ProgressEvent or StaticExportStep"
            )

    @classmethod
    def from_export(
        cls,
        event: ProgressEvent,
        *,
        view: str,
        runtime: StaticRuntime,
    ) -> StaticExportProgress:
        """Attach Studio identity to a marimo-export progress event."""
        return cls(view, runtime, event)

    @classmethod
    def from_step(
        cls,
        kind: StaticExportStepKind,
        *,
        view: str,
        runtime: StaticRuntime,
        completed: int | None = None,
        total: int | None = None,
        elapsed_seconds: float | None = None,
        message: str | None = None,
    ) -> StaticExportProgress:
        """Create one Studio-owned progress step with export identity."""
        return cls(
            view,
            runtime,
            StaticExportStep(
                kind,
                completed=completed,
                total=total,
                elapsed_seconds=elapsed_seconds,
                message=message,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "view": self.view,
            "runtime": self.runtime,
            "source": (
                "marimo-export"
                if isinstance(self.event, ProgressEvent)
                else "marimo-studio"
            ),
            "event": self.event.to_dict(),
        }

    def format_message(self) -> str:
        """Render one concise human progress line."""
        event = self.event
        label = event.kind.replace("_", " ").capitalize()
        if isinstance(event, ProgressEvent) and event.state is not None:
            label += f": {event.state}"
        if event.completed is not None and event.total is not None:
            label += f" ({event.completed}/{event.total})"
        if isinstance(event, ProgressEvent) and event.cache is not None:
            label += (
                f" | authored {event.cache.authored_hits} hit, "
                f"{event.cache.authored_misses} miss"
                f" | projections {event.cache.projection_hits} hit, "
                f"{event.cache.projection_misses} miss"
            )
        if event.elapsed_seconds is not None:
            label += f" | {event.elapsed_seconds:.3f}s"
        if event.message:
            label += f" | {event.message}"
        return label


__all__ = [
    "StaticExportEvent",
    "StaticExportProgress",
    "StaticExportStep",
    "StaticExportStepKind",
]
