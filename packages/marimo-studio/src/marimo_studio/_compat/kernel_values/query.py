"""Apply notebook query state through a Marimo session queue."""

from __future__ import annotations

from uuid import uuid4

from marimo_studio._compat.kernel_values.models import (
    NAMESPACE,
    QUERY_FUNCTION_NAME,
)
from marimo_studio._compat.server.models import ServerContext
from marimo_studio._compat.server.sessions import current_session
from marimo_studio.errors import ProtocolError


class QuerySyncUnavailable(ProtocolError):
    """The edit kernel cannot accept query state yet."""


def queue_query_sync(
    context: ServerContext,
    session_id: str,
    query: dict[str, str | list[str]],
    operation_id: str,
) -> None:
    """Queue one query-state update on the selected editor kernel."""
    from marimo._runtime.commands import InvokeFunctionCommand
    from marimo._session.capabilities import consumer_can
    from marimo._types.ids import RequestId

    session = current_session(context, session_id)
    consumer = session.room.main_consumer if session is not None else None
    if session is None or consumer is None:
        raise QuerySyncUnavailable("The Marimo editor session is still connecting.")
    if not consumer_can(
        session.room.get_capabilities(consumer),
        InvokeFunctionCommand,
    ):
        raise QuerySyncUnavailable(
            "The Marimo editor session cannot update query state."
        )
    session.put_control_request(
        InvokeFunctionCommand(
            function_call_id=RequestId(uuid4().hex),
            namespace=NAMESPACE,
            function_name=QUERY_FUNCTION_NAME,
            args={"query": query, "operation_id": operation_id},
        ),
        from_consumer_id=consumer.consumer_id,
    )
