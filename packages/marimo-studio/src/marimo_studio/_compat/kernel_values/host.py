"""Invoke projection operations through one selected Marimo session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from weakref import WeakKeyDictionary

from marimo_studio._compat.kernel_values.authorization import (
    BoundProjection,
    ProjectionAuthorizationError,
    RuntimeCellBinding,
)
from marimo_studio._compat.kernel_values.dependencies import (
    current_dependency_closure,
)
from marimo_studio._compat.kernel_values.query import sync_query_state
from marimo_studio._compat.kernel_values.session import (
    read_session_values,
    render_session_outputs,
)
from marimo_studio._compat.server.session_state import current_session
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import ResolvedProjection
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    ValueReadResult,
)
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio._server.records import ServerContext


@dataclass(frozen=True)
class _LiveProjectionState:
    signature: tuple[tuple[str, str], ...]
    graph: Any
    cells: tuple[RuntimeCellBinding, ...]


def _executed_signature(session: Any) -> tuple[tuple[str, str], ...]:
    executed_code = {
        str(cell_id): code
        for cell_id, code in session.session_view.last_executed_code.items()
    }
    return tuple(
        (runtime_id, executed_code[runtime_id])
        for row in session.document.cells
        if (runtime_id := str(row.id)) in executed_code
    )


def _build_live_projection_state(
    signature: tuple[tuple[str, str], ...],
) -> _LiveProjectionState:
    from marimo._ast.compiler import compile_cell
    from marimo._runtime.dataflow import DirectedGraph
    from marimo._types.ids import CellId_t

    current_refs = cell_refs(code for _runtime_id, code in signature)
    current_cells = tuple(
        RuntimeCellBinding(reference, runtime_id)
        for reference, (runtime_id, _code) in zip(
            current_refs,
            signature,
            strict=True,
        )
    )
    graph = DirectedGraph()
    try:
        for runtime_id, code in signature:
            cell_id = CellId_t(runtime_id)
            graph.register_cell(
                cell_id,
                compile_cell(code, cell_id=cell_id),
            )
    except Exception as error:
        raise ProjectionUnavailable(
            "stale-projection-binding",
            "The projection dependency closure changed after this "
            "presentation was published.",
            transient=False,
            status_code=409,
        ) from error
    return _LiveProjectionState(signature, graph, current_cells)


def _bind_projections(
    state: _LiveProjectionState,
    projections: tuple[ResolvedProjection, ...],
    runtime_cell_refs: Mapping[CellRef, str],
) -> tuple[BoundProjection, ...]:
    from marimo._types.ids import CellId_t

    bound: list[BoundProjection] = []
    for projection in projections:
        try:
            dependency_bindings = tuple(
                RuntimeCellBinding(reference, runtime_cell_refs[reference])
                for reference in projection.dependency_closure
            )
            producer = next(
                binding
                for binding in dependency_bindings
                if binding.cell_ref == projection.producer
            )
            current_closure = current_dependency_closure(
                state.graph,
                state.cells,
                producer.runtime_cell_id,
            )
        except (KeyError, StopIteration, ProjectionAuthorizationError) as error:
            raise ProjectionUnavailable(
                "stale-projection-binding",
                "The projection dependency closure changed after this "
                "presentation was published.",
                transient=False,
                status_code=409,
            ) from error
        cell = state.graph.cells.get(CellId_t(producer.runtime_cell_id))
        if (
            cell is None
            or tuple(binding.runtime_cell_id for binding in current_closure)
            != tuple(binding.runtime_cell_id for binding in dependency_bindings)
            or (
                projection.variable is not None and projection.variable not in cell.defs
            )
        ):
            raise ProjectionUnavailable(
                "stale-projection-binding",
                "The projection dependency closure changed after this "
                "presentation was published.",
                transient=False,
                status_code=409,
            )
        bound.append(BoundProjection(projection, dependency_bindings))
    return tuple(bound)


def _bind_live_projections(
    session: Any,
    projections: tuple[ResolvedProjection, ...],
    runtime_cell_refs: Mapping[CellRef, str],
) -> tuple[BoundProjection, ...]:
    return _bind_projections(
        _build_live_projection_state(_executed_signature(session)),
        projections,
        runtime_cell_refs,
    )


class PrivateKernelProjectionHost:
    """Read, render, and update one live kernel through its session queue."""

    def __init__(self) -> None:
        self._live_states: WeakKeyDictionary[Any, _LiveProjectionState] = (
            WeakKeyDictionary()
        )

    def _live_state(self, session: Any) -> _LiveProjectionState:
        signature = _executed_signature(session)
        current = self._live_states.get(session)
        if current is not None and current.signature == signature:
            return current
        current = _build_live_projection_state(signature)
        self._live_states[session] = current
        return current

    async def read_values(
        self,
        context: ServerContext,
        session_id: str,
        revision: str,
        projections: tuple[ResolvedProjection, ...],
        active_projections: tuple[ResolvedProjection, ...],
        *,
        consumer_id: str,
        runtime_cell_refs: Mapping[CellRef, str],
    ) -> ValueReadResult:
        session = current_session(context, session_id)
        if session is None:
            raise ProjectionUnavailable(
                "unknown-session",
                "The Marimo session is still connecting.",
                transient=True,
                status_code=409,
            )
        state = self._live_state(session)
        return await read_session_values(
            session,
            revision,
            _bind_projections(state, projections, runtime_cell_refs),
            _bind_projections(state, active_projections, runtime_cell_refs),
            consumer_id=consumer_id,
        )

    async def render_outputs(
        self,
        context: ServerContext,
        session_id: str,
        revision: str,
        projections: tuple[ResolvedProjection, ...],
        active_projections: tuple[ResolvedProjection, ...],
        *,
        consumer_id: str,
        runtime_cell_refs: Mapping[CellRef, str],
    ) -> OutputRenderResult:
        session = current_session(context, session_id)
        if session is None:
            raise ProjectionUnavailable(
                "unknown-session",
                "The Marimo session is still connecting.",
                transient=True,
                status_code=409,
            )
        state = self._live_state(session)
        return await render_session_outputs(
            session,
            revision,
            _bind_projections(state, projections, runtime_cell_refs),
            _bind_projections(state, active_projections, runtime_cell_refs),
            consumer_id=consumer_id,
        )

    async def sync_query(
        self,
        context: ServerContext,
        session_id: str,
        query: dict[str, str | list[str]],
        operation_id: str,
        *,
        binding_generation: int,
        query_generation: int,
        deadline: float,
    ) -> None:
        await sync_query_state(
            context,
            session_id,
            query,
            operation_id,
            binding_generation=binding_generation,
            query_generation=query_generation,
            deadline=deadline,
        )
