"""Structured results returned by Studio's agent-facing APIs."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

if TYPE_CHECKING:
    from marimo_studio.types import CheckResult

BrowserObservationState: TypeAlias = Literal[
    "ready",
    "loading",
    "error",
    "stale",
    "not-observed",
]
RuntimeStatusPhase: TypeAlias = Literal[
    "connecting",
    "synchronizing",
    "ready",
    "degraded",
    "failed",
]


def _phase_matches_diagnostics(
    phase: RuntimeStatusPhase,
    diagnostics: tuple[BrowserDiagnostic, ...],
) -> bool:
    if phase == "ready":
        return not diagnostics
    if phase in {"degraded", "failed"}:
        return bool(diagnostics)
    return True


@dataclass(frozen=True)
class BrowserDiagnostic:
    """One problem reported by a rendered Studio view."""

    code: str
    severity: Literal["warning", "error"]
    message: str
    hint: str
    view: str
    scope: str
    projection: Literal["cell", "value", "output"] | None = None
    target: str | None = None
    source: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "hint": self.hint,
            "view": self.view,
            "scope": self.scope,
        }
        if self.target is not None:
            value["target"] = self.target
        if self.projection is not None:
            value["projection"] = self.projection
        if self.source is not None:
            value["source"] = self.source
        return value


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    """Current runtime phase and its structured diagnostics."""

    phase: RuntimeStatusPhase
    diagnostics: tuple[BrowserDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class RuntimeStatusTransition:
    """One retained runtime phase change."""

    sequence: int
    observed_at: int
    phase: RuntimeStatusPhase
    revision: str | None = None
    session_id: str | None = None
    diagnostics: tuple[BrowserDiagnostic, ...] = ()
    diagnostics_truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "observed_at": self.observed_at,
            "revision": self.revision,
            "session_id": self.session_id,
            "phase": self.phase,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "diagnostics_truncated": self.diagnostics_truncated,
        }


@dataclass(frozen=True)
class RuntimeStatusReport:
    """Queryable current and recent runtime diagnostic state."""

    runtime: str
    view: str
    revision: str | None
    session_id: str | None
    current: RuntimeStatusSnapshot
    transitions: tuple[RuntimeStatusTransition, ...]

    @property
    def coherent(self) -> bool:
        if not 1 <= len(self.transitions) <= 32:
            return False
        if any(
            current.sequence <= previous.sequence
            for previous, current in pairwise(self.transitions)
        ):
            return False
        if any(
            transition.sequence < 0
            or transition.observed_at < 0
            or len(transition.diagnostics) > 20
            or not _phase_matches_diagnostics(
                transition.phase,
                transition.diagnostics,
            )
            for transition in self.transitions
        ):
            return False
        if len(self.current.diagnostics) > 200 or not _phase_matches_diagnostics(
            self.current.phase,
            self.current.diagnostics,
        ):
            return False
        diagnostics = (
            *self.current.diagnostics,
            *(
                diagnostic
                for transition in self.transitions
                for diagnostic in transition.diagnostics
            ),
        )
        if any(diagnostic.view != self.view for diagnostic in diagnostics):
            return False
        latest = self.transitions[-1]
        retained = self.current.diagnostics[:20]
        return (
            latest.phase == self.current.phase
            and latest.revision == self.revision
            and latest.session_id == self.session_id
            and latest.diagnostics == retained
            and latest.diagnostics_truncated
            == (len(retained) < len(self.current.diagnostics))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime": self.runtime,
            "view": self.view,
            "revision": self.revision,
            "session_id": self.session_id,
            "current": self.current.to_dict(),
            "transitions": [item.to_dict() for item in self.transitions],
        }


@dataclass(frozen=True)
class BrowserObservation:
    """Fresh browser evidence for one rendered view revision."""

    view: str
    state: BrowserObservationState
    runtime: str | None = None
    revision: str | None = None
    diagnostics: tuple[BrowserDiagnostic, ...] = ()
    message: str | None = None
    code: str | None = None
    client_id: str | None = None
    runtime_instance: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    sequence: int | None = None
    query: str | None = None
    runtime_status: RuntimeStatusReport | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "view": self.view,
            "state": self.state,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
        optional: tuple[tuple[str, object | None], ...] = (
            ("runtime", self.runtime),
            ("revision", self.revision),
            ("message", self.message),
            ("code", self.code),
            ("client_id", self.client_id),
            ("runtime_instance", self.runtime_instance),
            ("session_id", self.session_id),
            ("request_id", self.request_id),
            ("sequence", self.sequence),
            ("query", self.query),
            (
                "runtime_status",
                self.runtime_status.to_dict()
                if self.runtime_status is not None
                else None,
            ),
        )
        value.update((key, item) for key, item in optional if item is not None)
        return value


AnalysisStage: TypeAlias = Literal["analysis", "static", "runtime", "browser"]


@dataclass(frozen=True)
class AnalysisAction:
    """One repair step derived from a failed or warning validation."""

    stage: AnalysisStage
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


@dataclass(frozen=True)
class AnalysisReport:
    """Static, runtime, and rendered-browser evidence for Studio views."""

    notebook: Path
    views: tuple[str, ...]
    runtime: str
    revisions: dict[str, str]
    static_checks: tuple[CheckResult, ...]
    runtime_checks: tuple[CheckResult, ...]
    runtime_skipped: str | None
    browser_observations: tuple[BrowserObservation, ...]
    browser_required: bool
    actions: tuple[AnalysisAction, ...]

    @property
    def ok(self) -> bool:
        return self._error_count() == 0

    @property
    def handoff_ready(self) -> bool:
        if (
            not self.ok
            or not self.static_checks
            or not self.runtime_checks
            or self.runtime_skipped is not None
        ):
            return False
        if not self.browser_required:
            return True
        if len(self.browser_observations) != len(self.views):
            return False
        observations = {item.view: item for item in self.browser_observations}
        if len(observations) != len(self.browser_observations):
            return False
        return set(observations) == set(self.views) and all(
            observation.state == "ready"
            and observation.revision == self.revisions.get(view)
            and observation.runtime == self.runtime
            and bool(observation.runtime_instance)
            and bool(observation.client_id)
            and bool(observation.session_id)
            and bool(observation.request_id)
            and observation.sequence is not None
            and observation.sequence >= 0
            and observation.runtime_status is not None
            and observation.runtime_status.current.phase in {"ready", "degraded"}
            and observation.runtime_status.coherent
            and observation.runtime_status.runtime == observation.runtime
            and observation.runtime_status.view == view
            and observation.runtime_status.revision == observation.revision
            and observation.runtime_status.session_id == observation.session_id
            and observation.runtime_status.current.diagnostics
            == observation.diagnostics
            for view, observation in observations.items()
        )

    def to_dict(self) -> dict[str, object]:
        checks = (*self.static_checks, *self.runtime_checks)
        counts = {
            "pass": sum(result.status == "pass" for result in checks)
            + sum(
                observation.state == "ready"
                and not any(
                    diagnostic.severity == "error"
                    for diagnostic in observation.diagnostics
                )
                for observation in self.browser_observations
            ),
            "warn": self._warning_count(),
            "fail": self._error_count(),
        }
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "views": list(self.views),
            "runtime": self.runtime,
            "revisions": self.revisions,
            "ok": self.ok,
            "handoff_ready": self.handoff_ready,
            "summary": counts,
            "stages": {
                "static": {
                    "status": (
                        "fail"
                        if any(item.status == "fail" for item in self.static_checks)
                        else "pass"
                    ),
                    "checks": [item.to_dict() for item in self.static_checks],
                },
                "runtime": {
                    "status": (
                        "skipped"
                        if self.runtime_skipped is not None
                        else (
                            "fail"
                            if any(
                                item.status == "fail" for item in self.runtime_checks
                            )
                            else "pass"
                        )
                    ),
                    "reason": self.runtime_skipped,
                    "checks": [item.to_dict() for item in self.runtime_checks],
                },
                "browser": {
                    "required": self.browser_required,
                    "status": _browser_status(self.browser_observations),
                    "observations": [
                        item.to_dict() for item in self.browser_observations
                    ],
                },
            },
            "actions": [action.to_dict() for action in self.actions],
        }

    def _error_count(self) -> int:
        evidence = sum(
            result.status == "fail"
            for result in (*self.static_checks, *self.runtime_checks)
        )
        for observation in self.browser_observations:
            diagnostics = sum(
                diagnostic.severity == "error" for diagnostic in observation.diagnostics
            )
            evidence += diagnostics
            if observation.state == "error" and diagnostics == 0:
                evidence += 1
        actions = sum(action.severity == "error" for action in self.actions)
        return max(evidence, actions)

    def _warning_count(self) -> int:
        evidence = sum(
            result.status == "warn"
            for result in (*self.static_checks, *self.runtime_checks)
        ) + sum(
            diagnostic.severity == "warning"
            for observation in self.browser_observations
            for diagnostic in observation.diagnostics
        )
        actions = sum(action.severity == "warning" for action in self.actions)
        return max(evidence, actions)


def _browser_status(
    observations: tuple[BrowserObservation, ...],
) -> BrowserObservationState:
    if not observations:
        return "not-observed"
    for state in ("error", "stale", "loading", "not-observed"):
        if any(observation.state == state for observation in observations):
            return cast(BrowserObservationState, state)
    return "ready"


@dataclass(frozen=True)
class ViewActivationResult:
    """The browser transition completed or was scheduled after code mode exits."""

    notebook: Path
    view: str
    state: Literal["active", "reload-requested"]
    generation: int
    transition: Literal["in-place", "reload"]
    session_id: str
    client_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "state": self.state,
            "generation": self.generation,
            "transition": self.transition,
        }
        if self.client_id is not None:
            value["client_id"] = self.client_id
        value["session_id"] = self.session_id
        return value


__all__ = [
    "AnalysisAction",
    "AnalysisReport",
    "AnalysisStage",
    "BrowserDiagnostic",
    "BrowserObservation",
    "BrowserObservationState",
    "RuntimeStatusPhase",
    "RuntimeStatusReport",
    "RuntimeStatusSnapshot",
    "RuntimeStatusTransition",
    "ViewActivationResult",
]
