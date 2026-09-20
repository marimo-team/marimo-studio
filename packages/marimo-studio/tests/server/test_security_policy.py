from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from starlette.types import Message

from marimo_studio import create_asgi_app
from marimo_studio._composition import create_security_policy
from marimo_studio._server.headers import (
    edit_document_headers,
    edit_document_send,
    frame_ancestors_policy,
)
from marimo_studio._server.pages import error_response
from marimo_studio._server.security import (
    ALLOWED_EMBED_ORIGINS_ENV,
    SecurityPolicy,
    extend_security_policy_from_host_head,
    parse_allowed_embed_origins,
)
from marimo_studio.errors import ConfigurationError


def _origin_values(policy: SecurityPolicy) -> tuple[str, ...]:
    return tuple(origin.value for origin in policy.allowed_embed_origins)


def _origin_with_length(index: int, length: int) -> str:
    scheme = "https://"
    first = f"h{index}"
    remaining = length - len(scheme) - len(first)
    labels = [first]
    while remaining:
        label_length = min(63, remaining - 1)
        assert label_length > 0
        labels.append("a" * label_length)
        remaining -= label_length + 1
    return scheme + ".".join(labels)


def test_empty_configuration_preserves_same_origin_framing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ALLOWED_EMBED_ORIGINS_ENV, raising=False)

    policy = create_security_policy()

    assert policy == SecurityPolicy()
    assert frame_ancestors_policy(policy) == "frame-ancestors 'self'"
    assert edit_document_headers(policy)["Content-Security-Policy"] == (
        "frame-ancestors 'self'"
    )


def test_trusted_host_head_extends_the_embedding_policy() -> None:
    policy = extend_security_policy_from_host_head(
        parse_allowed_embed_origins("https://notebooks.example.com"),
        '<script data-parent-origin="HTTP://LOCALHOST:5175/"></script>'
        '<script data-parent-origin="invalid"></script>'
        '<div data-parent-origin="https://ignored.example.com"></div>',
    )

    assert _origin_values(policy) == (
        "https://notebooks.example.com",
        "http://localhost:5175",
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("http://localhost:55021", ("http://localhost:55021",)),
        (
            "http://localhost:55021,https://notebooks.example.com",
            ("http://localhost:55021", "https://notebooks.example.com"),
        ),
    ],
)
def test_allowed_embed_origins_are_added_after_self(
    source: str,
    expected: tuple[str, ...],
) -> None:
    policy = parse_allowed_embed_origins(source)

    assert _origin_values(policy) == expected
    assert frame_ancestors_policy(policy) == "frame-ancestors 'self' " + " ".join(
        expected
    )


def test_repair_document_uses_the_embedding_security_policy(tmp_path: Path) -> None:
    policy = parse_allowed_embed_origins("https://notebooks.example.com")

    response = error_response(
        "/studio/",
        ConfigurationError("Invalid workspace"),
        tmp_path / "notebook.py",
        base_url="",
        dev=True,
        edit_mode=True,
        structured=False,
        server_token="server-token",
        security_policy=policy,
    )

    assert response.headers["content-security-policy"] == (
        "frame-ancestors 'self' https://notebooks.example.com"
    )


def test_native_document_preserves_existing_content_security_directives() -> None:
    messages: list[Message] = []
    policy = parse_allowed_embed_origins("https://notebooks.example.com")

    async def send(message: Message) -> None:
        messages.append(message)

    async def exercise() -> None:
        await edit_document_send(send, policy)(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (
                        b"content-security-policy",
                        b"default-src 'self'; frame-ancestors 'none'; "
                        b"script-src 'self'",
                    )
                ],
            }
        )

    asyncio.run(exercise())

    headers = dict(messages[0].get("headers", ()))
    assert headers[b"content-security-policy"] == (
        b"default-src 'self'; script-src 'self'; "
        b"frame-ancestors 'self' https://notebooks.example.com"
    )


def test_allowed_embed_origins_are_canonicalized_and_deduplicated() -> None:
    policy = parse_allowed_embed_origins(
        " HTTPS://EXAMPLE.COM:443/, http://LOCALHOST:80,"
        "https://example.com,http://localhost:8080/,https://[2001:0DB8::1]:443/ "
    )

    assert _origin_values(policy) == (
        "https://example.com",
        "http://localhost",
        "http://localhost:8080",
        "https://[2001:db8::1]",
    )


def test_allowed_embed_origins_accept_the_configured_limits() -> None:
    origins = [*(_origin_with_length(index, 255) for index in range(15))]
    origins.append(_origin_with_length(15, 256))
    source = ",".join(origins)

    assert len(source.encode("utf-8")) == 4096
    assert len(_origin_values(parse_allowed_embed_origins(source))) == 16


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            ",".join("https://example.com" for _index in range(33)),
            f"{ALLOWED_EMBED_ORIGINS_ENV} contains 33 origin entries. Maximum is 32.",
        ),
        (
            ",".join(
                [
                    *(_origin_with_length(index, 255) for index in range(15)),
                    _origin_with_length(15, 257),
                ]
            ),
            f"{ALLOWED_EMBED_ORIGINS_ENV} contains 4097 UTF-8 bytes. Maximum is 4096.",
        ),
    ),
)
def test_allowed_embed_origins_reject_values_over_the_configured_limits(
    source: str,
    message: str,
) -> None:
    with pytest.raises(ConfigurationError) as captured:
        parse_allowed_embed_origins(source)

    assert str(captured.value) == message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("ftp://example.com", id="scheme"),
        pytest.param("example.com", id="missing-scheme"),
        pytest.param("https:///document", id="missing-hostname"),
        pytest.param("https://example.com/path", id="path"),
        pytest.param("https://example.com?query=1", id="query"),
        pytest.param("https://example.com?", id="empty-query"),
        pytest.param("https://example.com#fragment", id="fragment"),
        pytest.param("https://example.com#", id="empty-fragment"),
        pytest.param("https://user@example.com", id="username"),
        pytest.param("https://user:secret@example.com", id="password"),
        pytest.param("https://example.com\n", id="control-character"),
        pytest.param("https://example.com\x7f", id="delete-character"),
        pytest.param("https://example.com\x85", id="unicode-control-character"),
        pytest.param("https://*.example.com", id="wildcard"),
        pytest.param("https://example.com:abc", id="nonnumeric-port"),
        pytest.param("https://example.com:٤٤٣", id="non-ascii-port"),
        pytest.param("https://example.com:65536", id="out-of-range-port"),
        pytest.param("https://example.com:", id="empty-port"),
        pytest.param("https://exa mple.com", id="malformed-hostname"),
        pytest.param("https://127.0.0.999", id="malformed-address"),
        pytest.param("https://127.1", id="noncanonical-address"),
        pytest.param("https://0x7f000001", id="legacy-hex-address"),
        pytest.param("https://[::1]suffix", id="malformed-ipv6-authority"),
        pytest.param("https://éxample.com", id="non-ascii-hostname"),
        pytest.param(" ", id="empty-value"),
        pytest.param(",https://example.com", id="leading-empty-entry"),
        pytest.param("https://example.com,", id="trailing-empty-entry"),
        pytest.param("https://example.com,,https://other.example", id="empty-entry"),
    ],
)
def test_invalid_allowed_embed_origin_is_rejected(source: str) -> None:
    with pytest.raises(
        ConfigurationError,
        match=rf"^{ALLOWED_EMBED_ORIGINS_ENV} contains invalid origin ",
    ) as captured:
        parse_allowed_embed_origins(source)

    assert ALLOWED_EMBED_ORIGINS_ENV in str(captured.value)


def test_invalid_environment_configuration_fails_app_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offending = "https://example.com/embedded"
    monkeypatch.setenv(ALLOWED_EMBED_ORIGINS_ENV, offending)

    with pytest.raises(ConfigurationError) as captured:
        create_asgi_app(tmp_path / "notebook.py")

    assert str(captured.value) == (
        f"{ALLOWED_EMBED_ORIGINS_ENV} contains invalid origin {offending!r}"
    )


def test_entrypoint_middleware_uses_the_environment_policy() -> None:
    environment = {
        **os.environ,
        ALLOWED_EMBED_ORIGINS_ENV: "HTTPS://NOTEBOOKS.EXAMPLE.COM:443/",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; "
            "from marimo_studio._entrypoints import server_middleware; "
            "policy = server_middleware.kwargs['security_policy']; "
            "print(json.dumps([origin.value for origin in "
            "policy.allowed_embed_origins]))",
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert completed.stdout.strip() == json.dumps(["https://notebooks.example.com"])


def test_entrypoint_middleware_passes_export_owned_requests_to_marimo() -> None:
    environment = {
        **os.environ,
        "MARIMO_EXPORT_OWNED_SESSION": "1",
        ALLOWED_EMBED_ORIGINS_ENV: "invalid-origin",
    }
    script = textwrap.dedent(
        """
        import asyncio

        from marimo_studio._entrypoints import server_middleware

        async def marimo(scope, receive, send):
            del receive, send
            print(scope["path"])

        app = server_middleware.cls(marimo, **server_middleware.kwargs)
        asyncio.run(app({"type": "http", "path": "/api/sessions"}, None, None))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert completed.stdout.strip() == "/api/sessions"


def test_invalid_environment_configuration_fails_marimo_startup_concisely(
    notebook_path: Path,
) -> None:
    offending = "https://example.com/embedded"
    environment = {
        **os.environ,
        ALLOWED_EMBED_ORIGINS_ENV: offending,
    }
    completed = subprocess.run(
        [
            str(Path(sys.executable).with_name("marimo")),
            "edit",
            str(notebook_path),
            "--headless",
            "--no-token",
        ],
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )

    assert completed.returncode != 0
    assert completed.stderr.strip() == (
        f"Error: {ALLOWED_EMBED_ORIGINS_ENV} contains invalid origin {offending!r}"
    )
