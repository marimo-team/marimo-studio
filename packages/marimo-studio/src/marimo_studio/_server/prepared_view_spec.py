"""Resolve one Studio view into an explicit notebook export specification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from marimo_export import ExportPlan, ExportRepository, ExportSpec
from marimo_export.wire import portable_json, state_fingerprint

from marimo_studio._server.presentation import PresentationSnapshot
from marimo_studio._server.studio.view_compiler import (
    CompiledExportView,
    JsonValue,
    compile_export_view,
)
from marimo_studio.errors import PublicationError

_SAVED_SPEC = "export.yaml"


class PreparedSession(Protocol):
    """Public marimo-export session operations used by Studio."""

    def plan(
        self,
        *,
        spec: ExportSpec,
        repository: ExportRepository,
    ) -> ExportPlan: ...

    def observe_inputs(self) -> object: ...


@dataclass(frozen=True, slots=True)
class ResolvedPreparedView:
    compiled: CompiledExportView
    selected_inputs: Mapping[str, object] | None


def resolve_prepared_view(
    snapshot: PresentationSnapshot,
    session: PreparedSession,
    repository: ExportRepository,
) -> ResolvedPreparedView:
    """Resolve saved states or observed live states for one compiled view."""

    baseline = compile_export_view(snapshot)
    saved = _load_saved_spec(snapshot)
    initial = _compile_saved(snapshot, saved) if saved is not None else baseline
    plan = session.plan(spec=initial.spec, repository=repository)
    observed = session.observe_inputs()
    values = getattr(observed, "values", None)
    if not isinstance(values, Mapping):
        raise PublicationError("The live Marimo session returned invalid input values.")
    current = _project_inputs(values, plan.inputs)
    repository.record_observation(plan, current)
    if saved is not None:
        selected = current if _contains_state(plan, current) else None
        return ResolvedPreparedView(initial, selected)
    states = _observed_states(plan, current)
    return ResolvedPreparedView(
        compile_export_view(snapshot, states=states, default_state="baseline"),
        current,
    )


def _load_saved_spec(snapshot: PresentationSnapshot) -> ExportSpec | None:
    root = snapshot.resolved.views[snapshot.view_name].view.root
    source = root / _SAVED_SPEC
    if not source.exists() and not source.is_symlink():
        return None
    if source.is_symlink() or not source.is_file():
        raise PublicationError(f"The saved export specification is invalid: {source}")
    return ExportSpec.from_file(source)


def _compile_saved(
    snapshot: PresentationSnapshot,
    saved: ExportSpec,
) -> CompiledExportView:
    compiled = compile_export_view(
        snapshot,
        states=_portable_states(saved.states),
        default_state=saved.default_state,
    )
    saved_outputs = saved.to_value()["outputs"]
    compiled_outputs = compiled.spec.to_value()["outputs"]
    if saved_outputs != compiled_outputs:
        path = _saved_spec_path(snapshot)
        raise PublicationError(
            f"The saved export outputs do not match the current view: {path}"
        )
    return compiled


def _saved_spec_path(snapshot: PresentationSnapshot) -> Path:
    return snapshot.resolved.views[snapshot.view_name].view.root / _SAVED_SPEC


def _project_inputs(
    values: Mapping[object, object],
    inputs: tuple[str, ...],
) -> dict[str, JsonValue]:
    missing = [name for name in inputs if name not in values]
    if missing:
        raise PublicationError(
            f"The live Marimo session is missing export input {missing[0]!r}."
        )
    projected = portable_json(
        {name: values[name] for name in inputs},
        "Studio prepared inputs",
    )
    if not isinstance(projected, dict):
        raise AssertionError("Studio prepared inputs are not an object")
    return cast(dict[str, JsonValue], projected)


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


def _portable_states(
    states: Mapping[str, Mapping[str, object]],
) -> dict[str, Mapping[str, JsonValue]]:
    return {name: _portable_object(values) for name, values in states.items()}


def _portable_object(values: Mapping[str, object]) -> dict[str, JsonValue]:
    parsed = portable_json(values, "Studio prepared state")
    if not isinstance(parsed, dict):
        raise AssertionError("Studio prepared state is not an object")
    return cast(dict[str, JsonValue], parsed)


__all__ = ["ResolvedPreparedView", "resolve_prepared_view"]
