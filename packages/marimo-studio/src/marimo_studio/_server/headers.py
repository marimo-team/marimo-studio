"""Shared response headers for Studio documents and support routes."""

NO_STORE = {"Cache-Control": "no-store"}
DOCUMENT_HEADERS = {
    **NO_STORE,
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}
