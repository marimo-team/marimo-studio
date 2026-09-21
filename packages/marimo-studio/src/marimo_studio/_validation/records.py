"""Return one validation shape across static and runtime evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from marimo_studio._validation.evidence import ValidationIssue
from marimo_studio._validation.issues import check_issues
from marimo_studio._validation.results import CheckResult

if TYPE_CHECKING:
    from marimo_studio._validation.static import CheckReport

ValidationLevel = Literal["static", "runtime"]


@dataclass(frozen=True)
class ValidationReport:
    """Stable agent and CLI validation result with progressive evidence."""

    notebook: Path
    view: str | None
    level: ValidationLevel
    ok: bool
    issues: tuple[ValidationIssue, ...]
    evidence: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "level": self.level,
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_checks(
        cls,
        static: CheckReport,
        *,
        level: Literal["static", "runtime"],
        runtime: tuple[CheckResult, ...] = (),
    ) -> ValidationReport:
        evidence: dict[str, object] = {
            "static": {"checks": [item.to_dict() for item in static.checks]}
        }
        issues = check_issues(
            static.checks,
            "static",
            default_view=static.view,
        )
        if level == "runtime":
            evidence["runtime"] = {"checks": [item.to_dict() for item in runtime]}
            issues = (
                *issues,
                *check_issues(runtime, "runtime", default_view=static.view),
            )
        return cls(
            notebook=static.notebook,
            view=static.view,
            level=level,
            ok=not any(issue.severity == "error" for issue in issues),
            issues=issues,
            evidence=evidence,
        )
