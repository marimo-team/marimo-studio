"""Recompute mounted projection quotas and ownership."""

from __future__ import annotations

from marimo_studio._projections.resolution import (
    MAX_ACTIVE_PROJECTION_INSTANCES,
    MAX_UNIQUE_CELL_TARGETS,
    MAX_UNIQUE_OUTPUT_TARGETS,
    MAX_UNIQUE_VALUE_TARGETS,
    ResolvedProjection,
)
from marimo_studio._validation.evidence import ObservedProjectionInstance


def projection_policy_failures(
    instances: tuple[ObservedProjectionInstance, ...],
    resolved: dict[int, ResolvedProjection],
) -> dict[int, str]:
    """Return the policy failure expected for each mounted instance."""
    failures = {
        index: "projection-instance-limit"
        for index in resolved
        if index >= MAX_ACTIVE_PROJECTION_INSTANCES
    }
    limits = {
        "cell": MAX_UNIQUE_CELL_TARGETS,
        "output": MAX_UNIQUE_OUTPUT_TARGETS,
        "value": MAX_UNIQUE_VALUE_TARGETS,
    }
    unique: dict[str, list[str]] = {"cell": [], "output": [], "value": []}
    for index, instance in enumerate(instances):
        projection = resolved.get(index)
        if projection is None:
            continue
        kind = projection.kind
        targets = unique[kind]
        if instance.target not in targets:
            targets.append(instance.target)
        if index in failures:
            continue
        if targets.index(instance.target) >= limits[kind]:
            failures[index] = f"projection-{kind}-target-limit"

    cell_owners: set[str] = set()
    output_owners: set[str] = set()
    for index, projection in resolved.items():
        if index in failures:
            continue
        if projection.kind == "cell":
            producer = str(projection.producer)
            if producer in cell_owners:
                failures[index] = "duplicate-cell-host"
            cell_owners.add(producer)
        elif projection.kind == "output":
            target = projection.request.target
            if target in output_owners:
                failures[index] = "duplicate-output-host"
            output_owners.add(target)
    return failures
