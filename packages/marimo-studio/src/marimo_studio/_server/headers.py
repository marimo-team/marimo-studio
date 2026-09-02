"""Shared response headers for Studio documents and support routes."""

from starlette.types import Message, Send

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


def edit_document_send(send: Send, policy: SecurityPolicy) -> Send:
    """Apply frame ownership without discarding existing CSP directives."""
    frame_ancestors = frame_ancestors_policy(policy).encode()

    async def protected_send(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers: list[tuple[bytes, bytes]] = []
            framed = False
            for name, value in message.get("headers", ()):
                if name.lower() == b"content-security-policy":
                    directives = [
                        directive.strip()
                        for directive in value.split(b";")
                        if directive.strip()
                    ]
                    if any(
                        directive.split(maxsplit=1)[0].lower() == b"frame-ancestors"
                        for directive in directives
                    ):
                        framed = True
                        value = b"; ".join(
                            (
                                *(
                                    directive
                                    for directive in directives
                                    if directive.split(maxsplit=1)[0].lower()
                                    != b"frame-ancestors"
                                ),
                                frame_ancestors,
                            )
                        )
                headers.append((name, value))
            if not framed:
                headers.append((b"content-security-policy", frame_ancestors))
            message = {**message, "headers": headers}
        await send(message)

    return protected_send
