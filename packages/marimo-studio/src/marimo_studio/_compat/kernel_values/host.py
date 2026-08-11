"""Invoke projection operations through one selected Marimo session."""

from __future__ import annotations

from marimo_studio._capabilities import (
    ProjectionUnavailable,
    ServerContext,
)
from marimo_studio._compat.kernel_values.query import queue_query_sync
from marimo_studio._compat.kernel_values.session import (
    read_session_values,
    render_session_outputs,
)
from marimo_studio._compat.server.session_state import current_session
from marimo_studio.types import OutputRenderResult, ValueReadResult


class PrivateKernelProjectionHost:
    """Read, render, and update one live kernel through its session queue."""

    async def read_values(
        self,
        context: ServerContext,
        session_id: str,
        selectors: tuple[str, ...],
        *,
        consumer_id: str,
    ) -> ValueReadResult:
        session = current_session(context, session_id)
        if session is None:
            raise ProjectionUnavailable(
                "unknown-session",
                "The Marimo session is still connecting.",
                transient=True,
                status_code=409,
            )
        return await read_session_values(
            session,
            selectors,
            consumer_id=consumer_id,
        )

    async def render_outputs(
        self,
        context: ServerContext,
        session_id: str,
        selectors: tuple[str, ...],
        active_selectors: tuple[str, ...],
        *,
        consumer_id: str,
    ) -> OutputRenderResult:
        session = current_session(context, session_id)
        if session is None:
            raise ProjectionUnavailable(
                "unknown-session",
                "The Marimo session is still connecting.",
                transient=True,
                status_code=409,
            )
        return await render_session_outputs(
            session,
            selectors,
            active_selectors,
            consumer_id=consumer_id,
        )

    def sync_query(
        self,
        context: ServerContext,
        session_id: str,
        query: dict[str, str | list[str]],
        operation_id: str,
    ) -> None:
        queue_query_sync(context, session_id, query, operation_id)


__all__ = ["PrivateKernelProjectionHost"]
