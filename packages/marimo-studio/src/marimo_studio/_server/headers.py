"""Shared response headers for Studio documents and support routes."""

NO_STORE = {"Cache-Control": "no-store"}
DOCUMENT_HEADERS = {
    **NO_STORE,
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}
FRAME_ANCESTORS_SELF = "frame-ancestors 'self'"
EDIT_DOCUMENT_HEADERS = {
    **DOCUMENT_HEADERS,
    "Content-Security-Policy": FRAME_ANCESTORS_SELF,
}
