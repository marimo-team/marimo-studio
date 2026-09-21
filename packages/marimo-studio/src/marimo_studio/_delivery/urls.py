"""Build Studio URLs beneath Marimo's public base path."""

import base64
from collections.abc import Sequence
from pathlib import PurePosixPath
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

STUDIO_PATH = "/studio"
SUPPORT_PATH = "/_marimo-studio"
ACTIVE_VIEW_QUERY_PARAM = "marimo_studio_view"
STUDIO_CLIENT_QUERY_PARAM = "marimo_studio_client"
WORKSPACE_STREAM_QUERY_PARAM = "marimo_studio_connection"
WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM = "marimo_studio_events"
EDITOR_BINDING_CAPABILITY_QUERY_PARAM = "marimo_studio_editor"
SERVER_INSTANCE_QUERY_PARAM = "marimo_studio_server"
QUERY_OPERATION_QUERY_PARAM = "marimo_studio_query_operation"
DOCUMENT_LIFECYCLE_QUERY_PARAM = "marimo_studio_lifecycle"
PRESENTATION_RENEWAL_QUERY_PARAM = "marimo_studio_renewal"
DOCUMENT_REPLAY_QUERY_PARAM = "marimo_studio_resume"
EDITOR_SESSION_QUERY_PARAM = "marimo_studio_editor_session"
PRESENTATION_REVISION_QUERY_PARAM = "marimo_studio_revision"
UNFRAMED_QUERY_PARAM = "marimo_studio_unframed"
HOST_SESSION_HANDOFF_QUERY_PARAM = "marimo_studio_handoff"
PRIVATE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "file",
        "kiosk",
        ACTIVE_VIEW_QUERY_PARAM,
        DOCUMENT_LIFECYCLE_QUERY_PARAM,
        EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
        QUERY_OPERATION_QUERY_PARAM,
        PRESENTATION_RENEWAL_QUERY_PARAM,
        SERVER_INSTANCE_QUERY_PARAM,
        STUDIO_CLIENT_QUERY_PARAM,
        WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
        WORKSPACE_STREAM_QUERY_PARAM,
        DOCUMENT_REPLAY_QUERY_PARAM,
        HOST_SESSION_HANDOFF_QUERY_PARAM,
        UNFRAMED_QUERY_PARAM,
        PRESENTATION_REVISION_QUERY_PARAM,
        EDITOR_SESSION_QUERY_PARAM,
        "refresh_token",
        "session_id",
        "runtime",
    }
)


def public_url(base_url: str, path: str = "") -> str:
    """Join a root-relative path to Marimo's public base URL."""
    base_path = base_url.rstrip("/")
    suffix = path if path.startswith("/") or not path else f"/{path}"
    return f"{base_path}{suffix}" or "/"


def studio_url(base_url: str, view_name: str | None = None) -> str:
    """Return the public Studio workspace URL."""
    suffix = f"{STUDIO_PATH}/{view_name}/" if view_name else f"{STUDIO_PATH}/"
    return public_url(base_url, suffix)


def editor_url(
    base_url: str,
    file_key: str,
    query: Sequence[tuple[str, str]] = (),
    client_id: str | None = None,
    server_instance: str | None = None,
    session_id: str | None = None,
    binding_capability: str | None = None,
) -> str:
    """Return Marimo's native editor URL for one notebook."""
    parameters = _notebook_query(query)
    parameters.append(("file", file_key))
    if client_id is not None:
        parameters.append((STUDIO_CLIENT_QUERY_PARAM, client_id))
    if server_instance is not None:
        parameters.append((SERVER_INSTANCE_QUERY_PARAM, server_instance))
    if session_id is not None:
        parameters.append(("session_id", session_id))
    if binding_capability is not None:
        parameters.append((EDITOR_BINDING_CAPABILITY_QUERY_PARAM, binding_capability))
    return with_query(
        public_url(base_url, f"{SUPPORT_PATH}/editor/"),
        parameters,
    )


def with_notebook_query(
    url: str,
    query: Sequence[tuple[str, str]],
    routing_query: Sequence[tuple[str, str]] = (),
) -> str:
    """Append notebook-owned query parameters to a Studio URL."""
    return with_query(url, (*routing_query, *_notebook_query(query)))


def with_query(url: str, query: Sequence[tuple[str, str]]) -> str:
    """Merge query parameters into a public URL."""
    if not query:
        return url
    parts = urlsplit(url)
    parameters = [*parse_qsl(parts.query, keep_blank_values=True), *query]
    return urlunsplit((*parts[:3], urlencode(parameters), parts.fragment))


def _notebook_query(
    query: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    return [(key, value) for key, value in query if key not in PRIVATE_QUERY_KEYS]


def view_url(base_url: str, view_name: str) -> str:
    """Return the public standalone URL for a named view."""
    return public_url(base_url, f"/{view_name}/")


def artifact_view_url(
    base_url: str,
    view_name: str,
    artifact_revision: str,
) -> str:
    """Return the immutable browser base for one published view artifact."""
    revision = artifact_revision.removeprefix("sha256:")
    return public_url(
        base_url,
        f"/{view_name}/_marimo-studio/artifacts/{revision}/",
    )


def artifact_document_root_url(root_url: str, document: PurePosixPath) -> str:
    """Return the immutable browser base beside one artifact entry document."""
    parent = document.parent
    if parent == PurePosixPath("."):
        return root_url
    suffix = "/".join(quote(part, safe="") for part in parent.parts)
    return f"{root_url.rstrip('/')}/{suffix}/"


def authored_view_root_url(base_url: str, file_key: str) -> str:
    """Return the browser-native base for authored files in a directory app."""
    token = base64.urlsafe_b64encode(file_key.encode()).decode().rstrip("=")
    return public_url(base_url, f"{SUPPORT_PATH}/notebooks/{token}/views/")


def authored_file_key(token: str) -> str | None:
    """Decode a notebook key carried by an authored-file route."""
    try:
        padding = "=" * (-len(token) % 4)
        decoded = base64.b64decode(
            token + padding,
            altchars=b"-_",
            validate=True,
        ).decode()
    except (UnicodeDecodeError, ValueError):
        return None
    canonical = base64.urlsafe_b64encode(decoded.encode()).decode().rstrip("=")
    return decoded if canonical == token else None
