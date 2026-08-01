"""Read authorization and live session state from Marimo."""

from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.types import Scope

from marimo_studio._cell_refs import cell_refs
from marimo_studio._compat.server.models import ServerContext
from marimo_studio.errors import RuntimeSyncError
from marimo_studio.types import LiveCellIdentity, LiveCellSnapshot


def server_token_matches(scope: Scope, expected: str) -> bool:
    """Validate Marimo's server token for a Studio mutation route."""
    supplied = Headers(scope=scope).get("Marimo-Server-Token")
    return supplied is not None and hmac.compare_digest(supplied, expected)


def has_read_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    scopes = getattr(auth, "scopes", ())
    return "read" in scopes


def has_edit_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    scopes = getattr(auth, "scopes", ())
    return "edit" in scopes


def has_access_token(scope: Scope) -> bool:
    raw = scope.get("query_string", b"")
    query = parse_qs(bytes(raw).decode("latin-1"), keep_blank_values=True)
    return "access_token" in query


def current_session(context: ServerContext, session_id: str):
    from marimo._types.ids import SessionId

    return context._session_manager.get_session(SessionId(session_id))


def has_notebook_session(context: ServerContext) -> bool:
    """Return whether edit mode has a primary session for this notebook."""
    return (
        context._session_manager.get_session_by_file_key(context.file_key) is not None
    )


def live_cells(
    context: ServerContext,
    session_id: str | None,
) -> LiveCellSnapshot | None:
    """Read cell identities from one active Marimo document."""
    if session_id is not None:
        session = current_session(context, session_id)
    elif context.mode == "edit":
        session = context._session_manager.get_session_by_file_key(context.file_key)
    else:
        return None
    if session is None:
        if session_id is None or context.mode == "run":
            return None
        raise RuntimeSyncError(
            "The Marimo session is still connecting. Studio will retry shortly."
        )
    rows = tuple(session.document.cells)
    refs = cell_refs(row.code for row in rows)
    names: dict[str, list[LiveCellIdentity]] = {}
    for ref, row in zip(refs, rows, strict=True):
        if row.name == "_":
            continue
        names.setdefault(row.name, []).append(
            LiveCellIdentity(ref=ref, runtime_id=str(row.id))
        )
    return LiveCellSnapshot(
        ids={ref: str(row.id) for ref, row in zip(refs, rows, strict=True)},
        names={name: tuple(identities) for name, identities in names.items()},
    )
