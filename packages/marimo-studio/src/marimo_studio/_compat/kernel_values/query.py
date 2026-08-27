"""Apply notebook query state through an acknowledged Marimo kernel call."""

from __future__ import annotations

from marimo_studio._compat.kernel_values.models import (
    QUERY_FUNCTION_NAME,
)
from marimo_studio._compat.kernel_values.query_authorization import (
    authorized_query_arguments,
)
from marimo_studio._compat.kernel_values.session import _invoke_session_function
from marimo_studio._compat.server.session_state import current_session
from marimo_studio._server.presentation.ports import (
    ProjectionUnavailable,
    QuerySyncUnavailable,
)
from marimo_studio._server.presentation.query_state import query_fingerprint
from marimo_studio._server.records import ServerContext

_QUERY_SYNC_TIMEOUT_SECONDS = 5.0


async def sync_query_state(
    context: ServerContext,
    session_id: str,
    query: dict[str, str | list[str]],
    operation_id: str,
    *,
    binding_generation: int,
    query_generation: int,
    deadline: float,
) -> None:
    """Wait until the selected editor kernel applies one query update."""
    session = current_session(context, session_id)
    consumer = session.room.main_consumer if session is not None else None
    if session is None or consumer is None:
        raise QuerySyncUnavailable("The Marimo editor session is still connecting.")
    fingerprint = query_fingerprint(query)

    def parse(result: object) -> object:
        expected_identity = {
            "operation_id": operation_id,
            "fingerprint": fingerprint,
            "binding_generation": binding_generation,
            "query_generation": query_generation,
            "deadline": deadline,
        }
        if (
            not isinstance(result, dict)
            or {key: result.get(key) for key in expected_identity} != expected_identity
            or result.get("status") not in {"applied", "superseded", "expired"}
        ):
            raise ProjectionUnavailable(
                "invalid-query-response",
                "The Marimo kernel returned an invalid query acknowledgement.",
                transient=False,
            )
        return result

    try:
        result = await _invoke_session_function(
            session,
            function_name=QUERY_FUNCTION_NAME,
            args=authorized_query_arguments(
                query=query,
                fingerprint=fingerprint,
                operation_id=operation_id,
                binding_generation=binding_generation,
                query_generation=query_generation,
                deadline=deadline,
                session_id=session_id,
                notebook=context.notebook,
            ),
            consumer_id=str(consumer.consumer_id),
            timeout=_QUERY_SYNC_TIMEOUT_SECONDS,
            parser=parse,
            operation="query",
        )
        if isinstance(result, dict) and result.get("status") == "expired":
            raise QuerySyncUnavailable(
                "The queued query mutation expired before it could run."
            )
    except ProjectionUnavailable as error:
        raise QuerySyncUnavailable(str(error), terminal=error.terminal) from error
