"""Actionable issues from saved-source and runtime validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

ValidationStage: TypeAlias = Literal["validation", "static", "runtime"]


@dataclass(frozen=True)
class ValidationIssue:
    """One problem and repair step reported by validation."""

    stage: ValidationStage
    severity: Literal["warning", "error"]
    code: str
    message: str
    advice: str
    view: str | None = None
    target: str | None = None
    source: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "stage": self.stage,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "advice": self.advice,
        }
        if self.view is not None:
            value["view"] = self.view
        if self.target is not None:
            value["target"] = self.target
        if self.source is not None:
            value["source"] = self.source
        return value
