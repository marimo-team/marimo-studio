"""Protect how Studio applies the sandbox context of a marimohub session."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..helpers import write_marimohub_context
from .app_test_support import _studio_bootstrap


@pytest.mark.parametrize("persistence", ["workspace", "source", "none"])
def test_view_lists_report_what_the_hub_saves(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    persistence: str,
) -> None:
    write_marimohub_context(tmp_path, monkeypatch, persistence_mode=persistence)
    unconfigured = _marimo_app(notebook_path, programmatic=True)
    _edit_mode(unconfigured)
    configured = create_asgi_app(_configured(notebook_path).notebook)

    with TestClient(unconfigured) as client:
        first_view = client.get("/_marimo-studio/views").json()
    with TestClient(configured) as client:
        views = client.get("/_marimo-studio/views").json()

    assert first_view["persistence"] == persistence
    assert views["persistence"] == persistence


@pytest.mark.parametrize(
    "context",
    [
        None,
        "not json",
        "[" * 60_000,
        {"schema_version": 2},
        {"schema_version": True},
        {"persistence_mode": "everything"},
    ],
)
def test_view_lists_leave_persistence_unknown_without_a_valid_context(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context: str | dict[str, object] | None,
) -> None:
    if isinstance(context, dict):
        write_marimohub_context(tmp_path, monkeypatch, **context)
    else:
        path = tmp_path / "missing-or-invalid.json"
        if context is not None:
            path.write_text(context, encoding="utf-8")
        monkeypatch.setenv("MARIMOHUB_CONTEXT_FILE", str(path))
    app = create_asgi_app(_configured(notebook_path).notebook)

    with TestClient(app) as client:
        views = client.get("/_marimo-studio/views").json()

    assert views["persistence"] is None


def test_view_lists_read_a_context_that_the_hub_writes_after_startup(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "marimohub-context.json"
    monkeypatch.setenv("MARIMOHUB_CONTEXT_FILE", str(path))
    app = create_asgi_app(_configured(notebook_path).notebook)

    with TestClient(app) as client:
        before = client.get("/_marimo-studio/views").json()
        write_marimohub_context(tmp_path, monkeypatch, persistence_mode="source")
        after = client.get("/_marimo-studio/views").json()

    assert before["persistence"] is None
    assert after["persistence"] == "source"


def test_newer_hub_values_keep_the_fields_studio_reads(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MARIMO_STUDIO_TRUSTED_SERVER_RUNTIME", raising=False)
    write_marimohub_context(
        tmp_path, monkeypatch, exposure_mode="tunnel", persistence_mode="source"
    )
    app = _marimo_app(_configured(notebook_path).notebook, programmatic=True)
    _edit_mode(app)

    with TestClient(app) as client:
        views = client.get("/_marimo-studio/views").json()
        workspace = client.get("/studio/dashboard/?session_id=s_ready1")

    assert views["persistence"] == "source"
    assert _studio_bootstrap(workspace)["trustedServerRuntime"] is False


@pytest.mark.parametrize(
    ("exposure", "setting", "trusted"),
    [("proxy", "", True), ("subdomain", "", False), ("proxy", "0", False)],
)
def test_hub_origin_exposure_serves_server_views_on_the_hub_origin(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exposure: str,
    setting: str,
    trusted: bool,
) -> None:
    monkeypatch.setenv("MARIMO_STUDIO_TRUSTED_SERVER_RUNTIME", setting)
    write_marimohub_context(tmp_path, monkeypatch, exposure_mode=exposure)
    app = _marimo_app(_configured(notebook_path).notebook, programmatic=True)
    _edit_mode(app)

    with TestClient(app) as client:
        workspace = client.get("/studio/dashboard/?session_id=s_ready1")

    assert _studio_bootstrap(workspace)["trustedServerRuntime"] is trusted
