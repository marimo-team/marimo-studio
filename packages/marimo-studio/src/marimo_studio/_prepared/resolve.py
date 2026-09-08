"""Compose Studio's state space with compiler-owned prepared outputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from marimo_export import ExportPlan, ExportRepository, ExportSpec, StateSpace
from marimo_export.integration import KernelInputObservation
from marimo_export.progress import ProgressEvent
from marimo_export.wire import JsonValue, portable_json, state_fingerprint

from marimo_studio._prepared.compiler import CompiledExportView, compile_export_view
from marimo_studio._prepared.state_space import StateSpaceSource
from marimo_studio._server.presentation.service import PresentationSnapshot


class PreparedSession(Protocol):
    def plan(
        self,
        *,
        spec: ExportSpec,
        repository: ExportRepository,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> ExportPlan: ...

    def observe_inputs(
        self, *, plan: ExportPlan | None = None
    ) -> KernelInputObservation: ...


@dataclass(frozen=True, slots=True)
class ResolvedPreparedView:
    compiled: CompiledExportView
    selected_inputs: Mapping[str, object] | None


def resolve_prepared_view(
    snapshot: PresentationSnapshot,
    state_space_source: StateSpaceSource,
    session: PreparedSession,
    repository: ExportRepository,
    *,
    progress: Callable[[ProgressEvent], None] | None = None,
) -> ResolvedPreparedView:
    """Resolve configured or observed states for one immutable presentation."""
    state_space = state_space_source.state_space
    compiled = compile_export_view(
        snapshot.resolved,
        snapshot.view_name,
        snapshot.mounts,
        state_space=state_space,
    )
    plan = session.plan(spec=compiled.spec, repository=repository, progress=progress)
    current = _portable_object(session.observe_inputs(plan=plan).values)
    repository.record_observation(plan, current)
    if state_space is not None:
        selected = current if _contains_state(plan, current) else None
        return ResolvedPreparedView(compiled, selected)
    states = _observed_states(plan, current)
    return ResolvedPreparedView(
        compile_export_view(
            snapshot.resolved,
            snapshot.view_name,
            snapshot.mounts,
            state_space=StateSpace(default_state="baseline", states=states),
        ),
        current,
    )


def _contains_state(plan: ExportPlan, inputs: Mapping[str, object]) -> bool:
    fingerprint = state_fingerprint(inputs)
    return any(state.fingerprint == fingerprint for state in plan.states)


def _observed_states(
    plan: ExportPlan,
    current: Mapping[str, JsonValue],
) -> dict[str, Mapping[str, JsonValue]]:
    states: dict[str, Mapping[str, JsonValue]] = {"baseline": current}
    current_fingerprint = state_fingerprint(current)
    for observation in sorted(plan.observations, key=lambda item: item.fingerprint):
        values = _portable_object(observation.values)
        if observation.fingerprint == current_fingerprint:
            continue
        states[f"observed-{observation.fingerprint}"] = values
    return states


def _portable_object(values: Mapping[str, object]) -> dict[str, JsonValue]:
    parsed = portable_json(values, "Studio prepared state")
    if not isinstance(parsed, dict):
        raise AssertionError("Studio prepared state is not an object")
    return cast(dict[str, JsonValue], parsed)


__all__ = ["ResolvedPreparedView", "resolve_prepared_view"]
