from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.routing import Mount
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app

from ..app_helpers import configured


def test_live_runtime_config_does_not_expose_marimo_credentials(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    app = create_asgi_app(studio.notebook)
    mounted: Any = next(
        route.app for route in cast(Any, app).routes if isinstance(route, Mount)
    )
    user_config = deepcopy(mounted.state.config_manager.user_config_mgr.get_config())
    user_config["display"]["theme"] = "dark"
    user_config["server"]["disable_file_downloads"] = True
    user_config["completion"]["codeium_api_key"] = "leak-live-completion"
    user_config["ai"] = {
        "open_ai": {
            "api_key": "leak-live-ai",
            "extra_headers": {"Authorization": "leak-live-ai-header"},
        }
    }
    user_config["mcp"] = {
        "mcpServers": {
            "private": {
                "env": {"TOKEN": "leak-live-mcp-env"},
                "headers": {"Authorization": "leak-live-mcp-header"},
            }
        }
    }
    monkeypatch.setattr(
        mounted.state.config_manager.user_config_mgr,
        "get_config",
        lambda *, hide_secrets=True: user_config,
    )

    with TestClient(app) as client:
        response = client.get("/_marimo-studio/views/dashboard/config")

    assert response.status_code == 200
    assert response.json()["userConfig"]["display"]["theme"] == "dark"
    assert response.json()["userConfig"]["server"] == {"disable_file_downloads": True}
    assert "leak-live" not in response.text
