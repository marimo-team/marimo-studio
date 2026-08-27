"""Return one validation shape across static, runtime, and browser evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from marimo_studio._validation.actions import check_actions
from marimo_studio._validation.evidence import AnalysisAction, AnalysisReport
from marimo_studio._validation.results import CheckResult

if TYPE_CHECKING:
    from marimo_studio._validation.static import CheckReport

ValidationLevel = Literal["static", "runtime", "browser"]


@dataclass(frozen=True)
class ValidationReport:
    """Stable agent and CLI validation result with progressive evidence."""

    notebook: Path
    view: str | None
    level: ValidationLevel
    ok: bool
    actions: tuple[AnalysisAction, ...]
    evidence: Mapping[str, object]
    handoff_ready: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "level": self.level,
            "ok": self.ok,
            "handoff_ready": self.handoff_ready,
            "actions": [action.to_dict() for action in self.actions],
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
        actions = check_actions(
            static.checks,
            "static",
            default_view=static.view,
        )
        if level == "runtime":
            evidence["runtime"] = {"checks": [item.to_dict() for item in runtime]}
            actions = (
                *actions,
                *check_actions(runtime, "runtime", default_view=static.view),
            )
        return cls(
            notebook=static.notebook,
            view=static.view,
            level=level,
            ok=not any(action.severity == "error" for action in actions),
            actions=actions,
            evidence=evidence,
        )

    @classmethod
    def from_analysis(cls, report: AnalysisReport) -> ValidationReport:
        payload = report.to_dict()
        stages = payload["stages"]
        assert isinstance(stages, dict)
        return cls(
            notebook=report.notebook,
            view=report.views[0] if len(report.views) == 1 else None,
            level="browser",
            ok=report.ok,
            actions=report.actions,
            evidence={
                **stages,
                "revisions": report.revisions.copy(),
                "runtime_id": report.runtime,
            },
            handoff_ready=report.handoff_ready,
        )
