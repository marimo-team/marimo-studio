"""Build Studio URLs beneath Marimo's public base path."""

import base64
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STUDIO_PATH = "/studio"
SUPPORT_PATH = "/_marimo-studio"
PRIVATE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "file",
        "kiosk",
        "marimo_studio_resume",
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
) -> str:
    """Return Marimo's native editor URL for one notebook."""
    parameters = _notebook_query(query)
    parameters.append(("file", file_key))
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
