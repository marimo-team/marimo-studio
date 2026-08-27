from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager


def test_opaque_edit_repair_uses_a_view_scoped_capability_stream(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    events_scope: dict[str, object] = {}

    async def scoped_events(
        workspace: object,
        view_name: str | None = None,
        **_options: object,
    ) -> Any:
        events_scope.update(workspace=workspace, view=view_name)
        yield b"event: ready\ndata: {}\n\n"

    monkeypatch.setattr(
        "marimo_studio._server.support.change_events",
        scoped_events,
    )

    with TestClient(app) as client:
        assert client.get("/_marimo-studio/views/dashboard/config").status_code == 200
        studio.views["dashboard"].manifest.write_text(
            "this is not valid TOML =",
            encoding="utf-8",
        )
        repair = client.get(
            "/dashboard/",
            params={
                "marimo_studio_client": "browser-client-1234",
                "marimo_studio_lifecycle": "7",
            },
        )
        views = client.get("/_marimo-studio/views")
        encoded_events = re.search(r'new EventSource\(("[^"]+")\)', repair.text)
        assert encoded_events is not None
        events = client.get(json.loads(encoded_events.group(1)))

    assert repair.status_code == 500
    assert views.status_code == 200
    assert isinstance(views.json()["views"], list)
    assert "View needs repair" in repair.text
    assert "/_marimo-studio/presentation/" in repair.text
    assert "/_marimo-studio/dev/events" in repair.text
    assert events.status_code == 200
    assert events_scope == {"workspace": None, "view": "dashboard"}
    assert str(_session_manager(app).skew_protection_token) not in repair.text
