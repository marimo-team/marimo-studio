"""Validate compact browser mount facts against one server snapshot."""

from __future__ import annotations

from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ProjectionResolutionError,
    ResolvedProjection,
    resolve_projection,
)
from marimo_studio._server.presentation.evidence_policy import (
    projection_policy_failures,
)
from marimo_studio._server.presentation.service import PresentationSnapshot
from marimo_studio._server.runtime.catalog import RuntimeProjection
from marimo_studio._validation.evidence import (
    BrowserObservation,
    ObservedProjectionInstance,
)
from marimo_studio.errors import ProtocolError


def _runtime_binding_is_current(
    projection: ResolvedProjection,
    runtime: RuntimeProjection,
) -> bool:
    expected_runtime_ids: list[str] = []
    for reference in projection.dependency_closure:
        expected_ref = str(reference)
        runtime_cell_id = runtime.cell_refs.get(expected_ref)
        if runtime_cell_id is None:
            return False
        expected_runtime_ids.append(runtime_cell_id)
        current_value = runtime.current_cell_refs.get(runtime_cell_id)
        if current_value is None or CellRef.parse(current_value) != reference:
            return False
    producer_runtime_id = runtime.cell_refs.get(str(projection.producer))
    return producer_runtime_id is not None and runtime.dependency_closures.get(
        producer_runtime_id
    ) == tuple(expected_runtime_ids)


def _require_failure(instance: ObservedProjectionInstance, code: str) -> None:
    if (
        instance.phase not in {"error", "missing"}
        or instance.error is None
        or instance.error.get("code") != code
        or instance.runtime_cell_id is not None
    ):
        raise ProtocolError(
            "The browser mount failure does not match the server resolution."
        )


def _resolved_runtime_id(
    projection: ResolvedProjection,
    runtime: RuntimeProjection,
) -> str:
    runtime_id = runtime.cell_refs.get(str(projection.producer))
    if runtime_id is None:
        raise ProtocolError("The browser mount has no current runtime producer.")
    return runtime_id


def validate_projection_evidence(
    observation: BrowserObservation,
    snapshot: PresentationSnapshot,
    runtime: RuntimeProjection,
) -> None:
    """Derive mount authorization and runtime facts from compact browser state."""
    if (
        observation.revision != snapshot.revision
        or observation.runtime_instance != runtime.instance
    ):
        raise ProtocolError(
            "The browser mount evidence does not match its presentation revision."
        )
    resolved: dict[int, ResolvedProjection] = {}
    failures: dict[int, ProjectionResolutionError] = {}
    for index, instance in enumerate(observation.projection_instances):
        try:
            resolved[index] = resolve_projection(
                snapshot.symbols,
                snapshot.mounts,
                ProjectionRequest(
                    site_id=instance.mount_id or "",
                    instance_id=instance.instance_id,
                    target=instance.target,
                ),
            )
        except ProjectionResolutionError as error:
            failures[index] = error

    current = {
        index: projection
        for index, projection in resolved.items()
        if _runtime_binding_is_current(projection, runtime)
    }
    policy_failures = projection_policy_failures(
        observation.projection_instances,
        resolved,
    )
    for index, instance in enumerate(observation.projection_instances):
        resolution_error = failures.get(index)
        if resolution_error is not None:
            _require_failure(instance, resolution_error.code)
            continue
        projection = resolved[index]
        if index not in current:
            _require_failure(instance, "projection-runtime-binding-stale")
            continue
        policy_error = policy_failures.get(index)
        if policy_error is not None:
            _require_failure(instance, policy_error)
            continue
        expected_runtime_id = _resolved_runtime_id(projection, runtime)
        if instance.runtime_cell_id != expected_runtime_id:
            raise ProtocolError(
                "The browser mount runtime cell does not match the server snapshot."
            )
        if instance.phase == "ready" and instance.error is not None:
            raise ProtocolError("A ready browser mount cannot carry an error.")

    if observation.state == "ready" and not observation.projection_evidence_ready:
        raise ProtocolError("Ready browser evidence contains an unsettled mount.")
