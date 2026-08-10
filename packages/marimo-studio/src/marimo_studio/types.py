"""Studio-owned records shared across inspection and runtime boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias, cast

Scope: TypeAlias = MutableMapping[str, Any]
Message: TypeAlias = MutableMapping[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[Message]]
Send: TypeAlias = Callable[[Message], Awaitable[None]]


class ASGIApp(Protocol):
    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None: ...


@dataclass(frozen=True, order=True)
class CellRef:
    fingerprint: str
    layout_fingerprint: str
    occurrence: int = 0

    PREFIX = "cell:v1:"

    def __post_init__(self) -> None:
        fingerprint = self._digest(self.fingerprint)
        layout_fingerprint = self._digest(self.layout_fingerprint)
        if self.occurrence < 0:
            raise ValueError("Cell reference occurrence must be non-negative")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "layout_fingerprint", layout_fingerprint)

    @staticmethod
    def _digest(value: str) -> str:
        digest = value.lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Cell references require full SHA-256 digests")
        return digest

    @classmethod
    def parse(cls, value: CellRef | str) -> CellRef:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("Cell reference must be a string or CellRef")
        if not value.startswith(cls.PREFIX):
            raise ValueError(f"Invalid cell reference: {value}")
        payload, separator, occurrence = value.removeprefix(cls.PREFIX).rpartition(":")
        fingerprint, digest_separator, layout_fingerprint = payload.partition(":")
        if not separator or not digest_separator:
            raise ValueError(f"Invalid cell reference: {value}")
        try:
            occurrence_index = int(occurrence)
        except ValueError as error:
            raise ValueError(f"Invalid cell reference occurrence: {value}") from error
        return cls(fingerprint, layout_fingerprint, occurrence_index)

    def __str__(self) -> str:
        return (
            f"{self.PREFIX}{self.fingerprint}:{self.layout_fingerprint}:"
            f"{self.occurrence}"
        )


@dataclass(frozen=True)
class LiveCellIdentity:
    """One cell identity currently present in a Marimo session."""

    ref: CellRef
    runtime_id: str


@dataclass(frozen=True)
class LiveCellSnapshot:
    """Cell identities currently present in one Marimo session."""

    ids: Mapping[CellRef, str]
    names: Mapping[str, tuple[LiveCellIdentity, ...]]


@dataclass(frozen=True)
class SourceSpan:
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0


@dataclass(frozen=True)
class CellConfigSpec:
    column: int | None
    disabled: bool
    hide_code: bool


@dataclass(frozen=True)
class CellSpec:
    ref: CellRef
    runtime_id: str
    index: int
    name: str | None
    source: SourceSpan
    code_sha256: str
    preview: str
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    upstream: tuple[CellRef, ...]
    downstream: tuple[CellRef, ...]
    config: CellConfigSpec
    has_output_expression: bool
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["ref"] = str(self.ref)
        value["upstream"] = [str(ref) for ref in self.upstream]
        value["downstream"] = [str(ref) for ref in self.downstream]
        if self.code is None:
            value.pop("code")
        return value


ValuePathKind: TypeAlias = Literal["attribute", "item"]


@dataclass(frozen=True)
class ValuePathStep:
    kind: ValuePathKind
    value: str | int


@dataclass(frozen=True)
class ValueReference:
    source: str
    variable: str
    path: tuple[ValuePathStep, ...]


@dataclass(frozen=True)
class ValueBinding:
    reference: ValueReference
    cell: CellSpec
    source: Path
    line: int
    column: int


@dataclass(frozen=True)
class NotebookSpec:
    path: Path
    cells: tuple[CellSpec, ...]
    app_config: dict[str, Any]

    def by_ref(self) -> dict[CellRef, CellSpec]:
        return {cell.ref: cell for cell in self.cells}

    def named_cells(self) -> dict[str, CellSpec]:
        return {cell.name: cell for cell in self.cells if cell.name is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "notebook": str(self.path),
            "app_config": self.app_config,
            "cells": [cell.to_dict() for cell in self.cells],
        }


CheckStatus: TypeAlias = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    code: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.code is None:
            value.pop("code")
        if self.details is None:
            value.pop("details")
        return value


BrowserObservationState: TypeAlias = Literal[
    "ready",
    "loading",
    "error",
    "stale",
    "not-observed",
]


@dataclass(frozen=True)
class BrowserDiagnostic:
    """One problem reported by a rendered Studio view."""

    code: str
    severity: Literal["warning", "error"]
    message: str
    hint: str
    view: str
    scope: str
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
        if self.source is not None:
            value["source"] = self.source
        return value


@dataclass(frozen=True)
class BrowserObservation:
    """Readiness observed from one rendered view revision."""

    view: str
    state: BrowserObservationState
    runtime: str | None = None
    revision: str | None = None
    diagnostics: tuple[BrowserDiagnostic, ...] = ()
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "view": self.view,
            "state": self.state,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
        if self.runtime is not None:
            value["runtime"] = self.runtime
        if self.revision is not None:
            value["revision"] = self.revision
        if self.message is not None:
            value["message"] = self.message
        return value


@dataclass(frozen=True)
class AnalysisAction:
    """One repair step derived from a failed or warning validation."""

    stage: Literal["static", "runtime", "browser"]
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
    static_checks: tuple[CheckResult, ...]
    runtime_checks: tuple[CheckResult, ...]
    runtime_skipped: str | None
    browser_observations: tuple[BrowserObservation, ...]
    browser_required: bool
    actions: tuple[AnalysisAction, ...]

    @property
    def ok(self) -> bool:
        return (
            not any(
                result.status == "fail"
                for result in (*self.static_checks, *self.runtime_checks)
            )
            and not any(
                diagnostic.severity == "error"
                for observation in self.browser_observations
                for diagnostic in observation.diagnostics
            )
            and not any(
                observation.state == "error"
                for observation in self.browser_observations
            )
        )

    @property
    def handoff_ready(self) -> bool:
        if not self.ok or self.runtime_skipped is not None:
            return False
        if not self.browser_required:
            return True
        return bool(self.browser_observations) and all(
            observation.state == "ready" for observation in self.browser_observations
        )

    def to_dict(self) -> dict[str, object]:
        checks = (*self.static_checks, *self.runtime_checks)
        counts = {
            "pass": sum(result.status == "pass" for result in checks)
            + sum(
                observation.state == "ready"
                for observation in self.browser_observations
            ),
            "warn": sum(action.severity == "warning" for action in self.actions),
            "fail": sum(action.severity == "error" for action in self.actions),
        }
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "views": list(self.views),
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
    """A validated request to select one active browser view."""

    notebook: Path
    view: str
    state: Literal["requested"]
    generation: int
    transition: Literal["in-place", "reload"]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view": self.view,
            "state": self.state,
            "generation": self.generation,
            "transition": self.transition,
        }


@dataclass(frozen=True)
class ValueReadError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ValueReadResult:
    values: dict[str, object]
    errors: dict[str, ValueReadError]

    def to_dict(self) -> dict[str, object]:
        return {
            "values": self.values,
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
        }


@dataclass(frozen=True)
class RenderedOutput:
    owner_cell_id: str
    mimetype: str
    data: str
    timestamp: float
    reset_ui_object_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "ownerCellId": self.owner_cell_id,
            "mimetype": self.mimetype,
            "data": self.data,
            "timestamp": self.timestamp,
            "resetUiObjectIds": list(self.reset_ui_object_ids),
        }


@dataclass(frozen=True)
class OutputRenderResult:
    outputs: dict[str, RenderedOutput]
    errors: dict[str, ValueReadError]

    def to_dict(self) -> dict[str, object]:
        return {
            "outputs": {
                selector: output.to_dict() for selector, output in self.outputs.items()
            },
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
        }


@dataclass(frozen=True)
class RuntimeOutput:
    channel: str
    mimetype: str
    empty: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "mimetype": self.mimetype,
            "empty": self.empty,
        }


@dataclass(frozen=True)
class RuntimeCell:
    status: str | None
    outputs: tuple[RuntimeOutput, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "outputs": [output.to_dict() for output in self.outputs],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class RuntimeProbe:
    cells: dict[str, RuntimeCell]
    values: ValueReadResult
    outputs: OutputRenderResult
