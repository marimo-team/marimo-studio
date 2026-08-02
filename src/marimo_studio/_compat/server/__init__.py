"""Contain private Marimo server integrations behind one adapter surface."""

from marimo_studio._compat.server.context import (
    assert_supported_version,
    relative_request_path,
    server_context,
    server_location,
    server_shutdown_requested,
)
from marimo_studio._compat.server.models import (
    ServerContext,
    ServerLocation,
    ServerMode,
)
from marimo_studio._compat.server.peer_controls import enable_peer_control_sync
from marimo_studio._compat.server.programmatic import programmatic_middleware
from marimo_studio._compat.server.replay import (
    DOCUMENT_REPLAY_QUERY_PARAM,
    configure_document_replay,
)
from marimo_studio._compat.server.sessions import (
    current_session,
    has_access_token,
    has_edit_access,
    has_notebook_session,
    has_read_access,
    live_cells,
    server_token_matches,
)

__all__ = [
    "DOCUMENT_REPLAY_QUERY_PARAM",
    "ServerContext",
    "ServerLocation",
    "ServerMode",
    "assert_supported_version",
    "configure_document_replay",
    "current_session",
    "enable_peer_control_sync",
    "has_access_token",
    "has_edit_access",
    "has_notebook_session",
    "has_read_access",
    "live_cells",
    "programmatic_middleware",
    "relative_request_path",
    "server_context",
    "server_location",
    "server_shutdown_requested",
    "server_token_matches",
]
