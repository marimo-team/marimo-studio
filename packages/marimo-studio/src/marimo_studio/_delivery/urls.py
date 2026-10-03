"""Build Studio app paths and the browser references that address them.

An app path is a path-absolute reference beneath the server mount, such as
`/studio/dashboard/` or `/_marimo-studio/editor/?file=notebook.py`. It may carry
a query. Studio never writes the mount path into a browser URL.
`relative_url()` turns an app path into a reference that climbs from the
response that carries it to the mount root. The browser resolves that
reference against the URL it requested, so one response works at `/`, beneath
marimo's `--base-url`, and behind a proxy that adds or strips a path prefix.
"""

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


def relative_url(base: str, target: str) -> str:
    """Return a reference to app path `target` that resolves against `base`.

    `base` is the query-free, percent-encoded app path of the carrier: the
    requested path for a response, or the document base for references inside
    a document.
    """
    if not base.startswith("/") or not target.startswith("/"):
        raise ValueError("Studio references join two app paths")
    if "?" in base or "#" in base:
        raise ValueError("A reference base is a path without a query or fragment")
    depth = base[: base.rfind("/") + 1].count("/") - 1
    root = "../" * depth if depth else "./"
    return f"{root}{target[1:]}"


def studio_path(view_name: str | None = None) -> str:
    """Return the app path of the Studio workspace."""
    return f"{STUDIO_PATH}/{view_name}/" if view_name else f"{STUDIO_PATH}/"


def editor_path(
    file_key: str,
    query: Sequence[tuple[str, str]] = (),
    client_id: str | None = None,
    server_instance: str | None = None,
    session_id: str | None = None,
    binding_capability: str | None = None,
) -> str:
    """Return the app path of Marimo's native editor for one notebook."""
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
    return with_query(f"{SUPPORT_PATH}/editor/", parameters)


def with_notebook_query(
    url: str,
    query: Sequence[tuple[str, str]],
    routing_query: Sequence[tuple[str, str]] = (),
) -> str:
    """Append notebook-owned query parameters to a Studio URL."""
    return with_query(url, (*routing_query, *_notebook_query(query)))


def with_query(url: str, query: Sequence[tuple[str, str]]) -> str:
    """Merge query parameters into a URL reference."""
    if not query:
        return url
    parts = urlsplit(url)
    parameters = [*parse_qsl(parts.query, keep_blank_values=True), *query]
    return urlunsplit((*parts[:3], urlencode(parameters), parts.fragment))


def _notebook_query(
    query: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    return [(key, value) for key, value in query if key not in PRIVATE_QUERY_KEYS]


def view_path(view_name: str) -> str:
    """Return the app path of a named view's standalone document."""
    return f"/{view_name}/"


def artifact_path(view_name: str, artifact_revision: str) -> str:
    """Return the app path of one published view artifact."""
    revision = artifact_revision.removeprefix("sha256:")
    return f"/{view_name}{SUPPORT_PATH}/artifacts/{revision}/"


def artifact_document_root(root: str, document: PurePosixPath) -> str:
    """Return the directory that contains one artifact entry document."""
    parent = document.parent
    if parent == PurePosixPath("."):
        return root
    suffix = "/".join(quote(part, safe="") for part in parent.parts)
    return f"{root.rstrip('/')}/{suffix}/"


def authored_view_root_path(file_key: str) -> str:
    """Return the app path that authored files in a directory app resolve against."""
    token = base64.urlsafe_b64encode(file_key.encode()).decode().rstrip("=")
    return f"{SUPPORT_PATH}/notebooks/{token}/views/"


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
