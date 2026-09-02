"""Derive one exact dependency closure from a live Marimo graph."""

from __future__ import annotations

from typing import Any

from marimo_studio._compat.kernel_values.authorization import (
    STALE_PROJECTION_BINDING_MESSAGE,
    ProjectionAuthorizationError,
    RuntimeCellBinding,
)


def current_dependency_closure(
    graph: Any,
    cells: tuple[RuntimeCellBinding, ...],
    producer_runtime_id: str,
) -> tuple[RuntimeCellBinding, ...]:
    """Return the producer and live ancestors in document order."""
    graph_ids = {str(cell_id): cell_id for cell_id in graph.cells}
    producer_id = graph_ids.get(producer_runtime_id)
    if producer_id is None:
        raise ProjectionAuthorizationError(STALE_PROJECTION_BINDING_MESSAGE)
    required = {str(cell_id) for cell_id in graph.ancestors(producer_id)}
    required.add(producer_runtime_id)
    available = {binding.runtime_cell_id for binding in cells}
    if not required.issubset(available):
        raise ProjectionAuthorizationError(STALE_PROJECTION_BINDING_MESSAGE)
    return tuple(binding for binding in cells if binding.runtime_cell_id in required)
