"""Build Studio URLs beneath Marimo's public base path."""

from collections.abc import Sequence
from urllib.parse import urlencode

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
    return f"{public_url(base_url, '/')}?{urlencode(parameters)}"


def with_notebook_query(
    url: str,
    query: Sequence[tuple[str, str]],
) -> str:
    """Append notebook-owned query parameters to a Studio URL."""
    encoded = urlencode(_notebook_query(query))
    return f"{url}?{encoded}" if encoded else url


def _notebook_query(
    query: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    return [(key, value) for key, value in query if key not in PRIVATE_QUERY_KEYS]


def view_url(base_url: str, view_name: str) -> str:
    """Return the public standalone URL for a named view."""
    return public_url(base_url, f"/{view_name}/")
