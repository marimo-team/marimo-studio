"""Authenticate presentation requests before they enter a live kernel.

The server resolves each allowed notebook target and signs it together with
the presentation revision and current runtime-cell mapping. The kernel verifies
that permission and recomputes the live dependency path before reading values
or formatting native output. A tampered request or stale page therefore cannot
read notebook state from a newer presentation.

Output permissions also follow the browser's current mounted set. Isolated
runtime probes use a separate short-lived lease for the exact selectors being
validated.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass

from marimo_studio._compat.kernel_values.authorization_key import (
    projection_authorization_key,
)
from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import ResolvedProjection
from marimo_studio._server.presentation.ports import SelectorSpec


class ProjectionAuthorizationError(ValueError):
    """A kernel projection call lacks a valid server capability."""


STALE_PROJECTION_BINDING_MESSAGE = (
    "The authorized projection dependency closure is stale."
)


@dataclass(frozen=True)
class RuntimeCellBinding:
    """One semantic dependency joined to its current session cell."""

    cell_ref: CellRef
    runtime_cell_id: str


@dataclass(frozen=True)
class BoundProjection:
    """A resolved projection joined to its complete live dependency closure."""

    projection: ResolvedProjection
    dependency_bindings: tuple[RuntimeCellBinding, ...]

    def __post_init__(self) -> None:
        expected = self.projection.dependency_closure
        actual = tuple(binding.cell_ref for binding in self.dependency_bindings)
        runtime_ids = tuple(
            binding.runtime_cell_id for binding in self.dependency_bindings
        )
        if actual != expected:
            raise ValueError(
                "Projection dependency bindings must match the resolved closure."
            )
        if any(not runtime_id for runtime_id in runtime_ids) or len(
            set(runtime_ids)
        ) != len(runtime_ids):
            raise ValueError(
                "Projection dependency bindings require distinct runtime cells."
            )

    @property
    def producer_binding(self) -> RuntimeCellBinding:
        return next(
            binding
            for binding in self.dependency_bindings
            if binding.cell_ref == self.projection.producer
        )


@dataclass(frozen=True)
class ProjectionBinding:
    producer: CellRef
    runtime_cell_id: str
    dependency_closure: tuple[RuntimeCellBinding, ...]


@dataclass(frozen=True)
class AuthorizedProjections:
    specifications: dict[str, SelectorSpec]
    bindings: dict[str, ProjectionBinding]


def _projection_record(bound: BoundProjection) -> dict[str, object]:
    projection = bound.projection
    producer = bound.producer_binding
    return {
        "siteId": projection.request.site_id,
        "instanceId": projection.request.instance_id,
        "kind": projection.kind,
        "target": projection.request.target,
        "specification": projection.selector_spec(),
        "producer": str(projection.producer),
        "runtimeCellId": producer.runtime_cell_id,
        "dependencyClosure": [
            {
                "cellRef": str(binding.cell_ref),
                "runtimeCellId": binding.runtime_cell_id,
            }
            for binding in bound.dependency_bindings
        ],
    }


def _probe_records(
    kind: str,
    specifications: Mapping[str, SelectorSpec],
) -> list[dict[str, object]]:
    return [
        {
            "siteId": "probe",
            "instanceId": f"probe-{kind}-{index}",
            "kind": kind,
            "target": target,
            "specification": specification,
            "producer": None,
            "runtimeCellId": None,
            "dependencyClosure": None,
        }
        for index, (target, specification) in enumerate(specifications.items())
    ]


def _payload(
    operation: str,
    revision: str,
    projections: list[dict[str, object]],
    *,
    active_projections: list[dict[str, object]] | None = None,
    consumer_id: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "operation": operation,
        "revision": revision,
        "projections": projections,
    }
    if active_projections is not None:
        value["activeProjections"] = active_projections
    if consumer_id is not None:
        value["consumerId"] = consumer_id
    return value


def _signature(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(projection_authorization_key(), encoded, hashlib.sha256).hexdigest()


def authorized_value_arguments(
    revision: str,
    projections: tuple[BoundProjection, ...],
) -> dict[str, object]:
    """Serialize one server-authorized value call for the kernel queue."""
    records = [_projection_record(projection) for projection in projections]
    payload = _payload("value", revision, records)
    return {
        "revision": revision,
        "projections": records,
        "authorization": _signature(payload),
    }


def authorized_output_arguments(
    revision: str,
    projections: tuple[BoundProjection, ...],
    active_projections: tuple[BoundProjection, ...],
    consumer_id: str,
) -> dict[str, object]:
    """Serialize one server-authorized output call for the kernel queue."""
    records = [_projection_record(projection) for projection in projections]
    active = [_projection_record(projection) for projection in active_projections]
    payload = _payload(
        "output",
        revision,
        records,
        active_projections=active,
        consumer_id=consumer_id,
    )
    return {
        "revision": revision,
        "projections": records,
        "active_projections": active,
        "consumer_id": consumer_id,
        "authorization": _signature(payload),
    }


def probe_value_arguments(
    specifications: Mapping[str, SelectorSpec],
) -> dict[str, object]:
    """Serialize selectors owned by an active internal probe lease."""
    return {
        "revision": "probe",
        "projections": _probe_records("value", specifications),
        "authorization": "",
    }


def probe_output_arguments(
    specifications: Mapping[str, SelectorSpec],
    active_specifications: Mapping[str, SelectorSpec],
    consumer_id: str,
) -> dict[str, object]:
    """Serialize output selectors owned by an active internal probe lease."""
    return {
        "revision": "probe",
        "projections": _probe_records("output", specifications),
        "active_projections": _probe_records("output", active_specifications),
        "consumer_id": consumer_id,
        "authorization": "",
    }


def _decode_records(
    value: object,
    *,
    kind: str,
) -> tuple[dict[str, SelectorSpec], dict[str, ProjectionBinding | None]]:
    from marimo_studio._compat.kernel_values.selectors import normalize_selector_spec

    if not isinstance(value, list):
        raise ProjectionAuthorizationError("Projection records must be an array.")
    specifications: dict[str, SelectorSpec] = {}
    bindings: dict[str, ProjectionBinding | None] = {}
    for record in value:
        if not isinstance(record, dict) or set(record) != {
            "siteId",
            "instanceId",
            "kind",
            "target",
            "specification",
            "producer",
            "runtimeCellId",
            "dependencyClosure",
        }:
            raise ProjectionAuthorizationError("A projection record is invalid.")
        if (
            not isinstance(record["siteId"], str)
            or not record["siteId"]
            or not isinstance(record["instanceId"], str)
            or not record["instanceId"]
            or record["kind"] != kind
            or not isinstance(record["target"], str)
            or not record["target"]
        ):
            raise ProjectionAuthorizationError("A projection record is invalid.")
        target = record["target"]
        assert isinstance(target, str)
        producer = record["producer"]
        runtime_cell_id = record["runtimeCellId"]
        dependency_closure = record["dependencyClosure"]
        unbound = (
            producer is None and runtime_cell_id is None and dependency_closure is None
        )
        if not unbound and (
            not isinstance(producer, str)
            or not producer
            or not isinstance(runtime_cell_id, str)
            or not runtime_cell_id
            or not isinstance(dependency_closure, list)
            or not dependency_closure
        ):
            raise ProjectionAuthorizationError("A projection binding is invalid.")
        try:
            specification = normalize_selector_spec(target, record["specification"])
        except (TypeError, ValueError) as error:
            raise ProjectionAuthorizationError(
                "A projection selector does not match its target."
            ) from error
        previous = specifications.get(target)
        binding: ProjectionBinding | None = None
        if not unbound:
            assert isinstance(producer, str)
            assert isinstance(runtime_cell_id, str)
            assert isinstance(dependency_closure, list)
            try:
                producer_ref = CellRef.parse(producer)
                cells = tuple(
                    RuntimeCellBinding(
                        CellRef.parse(item["cellRef"]),
                        item["runtimeCellId"],
                    )
                    for item in dependency_closure
                    if isinstance(item, dict)
                    and set(item) == {"cellRef", "runtimeCellId"}
                    and isinstance(item["cellRef"], str)
                    and isinstance(item["runtimeCellId"], str)
                    and item["runtimeCellId"]
                )
            except ValueError as error:
                raise ProjectionAuthorizationError(
                    "A projection dependency binding is invalid."
                ) from error
            if len(cells) != len(dependency_closure):
                raise ProjectionAuthorizationError(
                    "A projection dependency binding is invalid."
                )
            refs = tuple(item.cell_ref for item in cells)
            runtime_ids = tuple(item.runtime_cell_id for item in cells)
            producer_cells = tuple(
                item for item in cells if item.cell_ref == producer_ref
            )
            if (
                len(set(refs)) != len(refs)
                or len(set(runtime_ids)) != len(runtime_ids)
                or len(producer_cells) != 1
                or producer_cells[0].runtime_cell_id != runtime_cell_id
            ):
                raise ProjectionAuthorizationError(
                    "A projection dependency binding is invalid."
                )
            binding = ProjectionBinding(producer_ref, runtime_cell_id, cells)
        if previous is not None and (
            previous != specification or bindings[target] != binding
        ):
            raise ProjectionAuthorizationError(
                "Repeated projection targets require identical selectors."
            )
        specifications[target] = specification
        bindings[target] = binding
    return specifications, bindings


def _authorized_projections(
    specifications: dict[str, SelectorSpec],
    bindings: dict[str, ProjectionBinding | None],
) -> AuthorizedProjections:
    if any(binding is None for binding in bindings.values()):
        raise ProjectionAuthorizationError(
            "Projection authorization lacks a live binding."
        )
    return AuthorizedProjections(
        specifications,
        {
            target: binding
            for target, binding in bindings.items()
            if binding is not None
        },
    )


def verify_value_arguments(
    *,
    revision: object,
    projections: object,
    authorization: object,
    probe_targets: tuple[str, ...] | None = None,
) -> AuthorizedProjections:
    """Verify one value capability and return its canonical selectors."""
    specifications, bindings = _decode_records(projections, kind="value")
    assert isinstance(projections, list)
    if revision == "probe" and authorization == "" and probe_targets is not None:
        if set(specifications).issubset(probe_targets) and all(
            binding is None for binding in bindings.values()
        ):
            return AuthorizedProjections(specifications, {})
        raise ProjectionAuthorizationError("A selector is outside the probe lease.")
    if (
        not isinstance(revision, str)
        or not revision
        or not isinstance(authorization, str)
    ):
        raise ProjectionAuthorizationError("Projection authorization is invalid.")
    payload = _payload("value", revision, list(projections))
    if not hmac.compare_digest(authorization, _signature(payload)):
        raise ProjectionAuthorizationError("Projection authorization is invalid.")
    return _authorized_projections(specifications, bindings)


def verify_output_arguments(
    *,
    revision: object,
    projections: object,
    active_projections: object,
    consumer_id: object,
    authorization: object,
    probe_targets: tuple[str, ...] | None = None,
) -> tuple[AuthorizedProjections, AuthorizedProjections]:
    """Verify one output capability and return its canonical selectors."""
    specifications, bindings = _decode_records(projections, kind="output")
    active, active_bindings = _decode_records(active_projections, kind="output")
    assert isinstance(projections, list)
    assert isinstance(active_projections, list)
    if not isinstance(consumer_id, str) or not consumer_id:
        raise ProjectionAuthorizationError("The output consumer is invalid.")
    if revision == "probe" and authorization == "" and probe_targets is not None:
        if (
            set((*specifications, *active)).issubset(probe_targets)
            and all(binding is None for binding in bindings.values())
            and all(binding is None for binding in active_bindings.values())
        ):
            return AuthorizedProjections(specifications, {}), AuthorizedProjections(
                active, {}
            )
        raise ProjectionAuthorizationError("A selector is outside the probe lease.")
    if (
        not isinstance(revision, str)
        or not revision
        or not isinstance(authorization, str)
    ):
        raise ProjectionAuthorizationError("Projection authorization is invalid.")
    payload = _payload(
        "output",
        revision,
        list(projections),
        active_projections=list(active_projections),
        consumer_id=consumer_id,
    )
    if not hmac.compare_digest(authorization, _signature(payload)):
        raise ProjectionAuthorizationError("Projection authorization is invalid.")
    return _authorized_projections(specifications, bindings), _authorized_projections(
        active, active_bindings
    )
