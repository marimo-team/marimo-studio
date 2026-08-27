"""Authorize one trusted native-editor binding."""

from __future__ import annotations

import hashlib
import hmac
import json
import re

from marimo_studio._server.records import ServerContext
from marimo_studio._server.server_instance import server_instance_id

_CAPABILITY_PATTERN = re.compile(r"[0-9a-f]{64}")
_PURPOSE = "marimo-studio-editor-binding-v1"


def editor_binding_capability(
    server_token: str,
    file_key: str,
    base_url: str,
    client_id: str,
    session_id: str,
) -> str:
    """Sign editor-binding authority for one client and native session."""
    audience = json.dumps(
        (
            _PURPOSE,
            file_key,
            base_url,
            "edit",
            client_id,
            server_instance_id(server_token),
            session_id,
        ),
        separators=(",", ":"),
    ).encode()
    return hmac.new(server_token.encode(), audience, hashlib.sha256).hexdigest()


def editor_binding_capability_matches(
    token: str | None,
    context: ServerContext,
    client_id: str,
    session_id: str,
) -> bool:
    """Validate exact editor-binding authority for this server context."""
    if (
        context.mode != "edit"
        or token is None
        or _CAPABILITY_PATTERN.fullmatch(token) is None
    ):
        return False
    expected = editor_binding_capability(
        context.server_token,
        context.file_key,
        context.base_url,
        client_id,
        session_id,
    )
    return hmac.compare_digest(token, expected)
