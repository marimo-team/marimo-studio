from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from marimo._server.api import middleware
from starlette.testclient import TestClient

from marimo_studio._compat.server.presentation_auth import (
    PrivatePresentationAuthorization,
)

from ..app_helpers import marimo_app, session_manager


def test_presentation_authorization_redacts_invalid_skew_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def warning(message: object, *args: object, **kwargs: Any) -> None:
        warnings.append((message, args, kwargs))

    monkeypatch.setattr(middleware.LOGGER, "warning", warning)
    authorization = PrivatePresentationAuthorization()
    handle = authorization.open()
    try:
        middleware.LOGGER.warning(
            "Received request with invalid server token (skew protection token). "
            "This could mean the server has new code deployed but the client is "
            "still using an old version.Expected: expected-secret, got: supplied-secret"
        )
        middleware.LOGGER.warning("Another warning: %s", "public-value")
    finally:
        handle.close()

    assert warnings == [
        (
            "Received request with invalid server token (skew protection token). "
            "This could mean the server has new code deployed but the client is "
            "still using an old version.",
            (),
            {},
        ),
        ("Another warning: %s", ("public-value",), {}),
    ]
    assert "expected-secret" not in repr(warnings)
    assert "supplied-secret" not in repr(warnings)
    assert middleware.LOGGER.warning is warning


def test_invalid_skew_request_does_not_log_either_token(
    notebook_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = marimo_app(notebook_path, skew_protection=True)
    expected_token = str(session_manager(app).skew_protection_token)
    authorization = PrivatePresentationAuthorization()
    handle = authorization.open()
    caplog.set_level("WARNING", logger="marimo")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/unknown",
                headers={"Marimo-Server-Token": "supplied-secret"},
            )
    finally:
        handle.close()

    assert response.status_code == 401
    assert "Received request with invalid server token" in caplog.text
    assert expected_token not in caplog.text
    assert "supplied-secret" not in caplog.text
