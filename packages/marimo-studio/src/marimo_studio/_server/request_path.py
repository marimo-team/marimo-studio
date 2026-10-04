"""Address responses relative to the URL that the browser requested.

The middleware records each request's app path before capability, alias, and
editor routing rewrite the ASGI path. Handlers build references from that
recorded path, so a redirect or document resolves beneath whatever path prefix
the browser used to reach the server.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

from starlette.requests import HTTPConnection
from starlette.types import Scope

from marimo_studio._delivery.urls import relative_url

REQUEST_PATH_SCOPE_KEY = "marimo_studio.request_path"
# RFC 3986 path characters. `%` keeps the browser's existing escapes.
_PATH_CHARACTERS = "/%:@!$&'()*+,;=-._~"


def with_request_path(scope: Scope, relative: str) -> Scope:
    """Record the app path of the request that the browser sent.

    `relative` is the decoded routing path beneath the server mount. The
    recorded path keeps the browser's percent-encoding, so an encoded slash
    stays inside its segment when Studio counts directory depth.
    """
    raw = scope.get("raw_path")
    encoded = (
        quote(raw.decode("latin-1"), safe=_PATH_CHARACTERS)
        if isinstance(raw, bytes)
        else quote(relative, safe=_PATH_CHARACTERS.replace("%", ""))
    )
    start = 0
    while start != -1:
        if unquote(encoded[start:]) == relative:
            return {**scope, REQUEST_PATH_SCOPE_KEY: encoded[start:]}
        start = encoded.find("/", start + 1)
    return {**scope, REQUEST_PATH_SCOPE_KEY: quote(relative, safe="/")}


def request_path(connection: HTTPConnection) -> str:
    """Return the app path of the request that the browser sent."""
    try:
        return connection.scope[REQUEST_PATH_SCOPE_KEY]
    except KeyError:
        raise RuntimeError(
            "PresentationMiddleware records the request path before Studio "
            "handlers run."
        ) from None


def request_reference(connection: HTTPConnection, target: str) -> str:
    """Return a reference to app path `target` from the requested URL."""
    return relative_url(request_path(connection), target)
