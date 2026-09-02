"""Shared response headers for Studio documents and support routes."""

from marimo_studio._server.security import SecurityPolicy

NO_STORE = {"Cache-Control": "no-store"}
DOCUMENT_HEADERS = {
    **NO_STORE,
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}


def frame_ancestors_policy(policy: SecurityPolicy) -> str:
    """Serialize the allowed parents for Studio edit documents."""
    sources = ("'self'", *(origin.value for origin in policy.allowed_embed_origins))
    return f"frame-ancestors {' '.join(sources)}"


def edit_document_headers(policy: SecurityPolicy) -> dict[str, str]:
    """Return response headers for a Studio edit document."""
    return {
        **DOCUMENT_HEADERS,
        "Content-Security-Policy": frame_ancestors_policy(policy),
    }
