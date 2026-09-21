from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._browser_client.protocol import (
    parse_connection_token,
    parse_show_result,
)
from marimo_studio._browser_client.records import ShowResult
from marimo_studio.errors import ProtocolError

pytestmark = pytest.mark.supported_python


def test_connection_protocol_requires_the_target_notebook(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = {
        "schema": 1,
        "notebook": str(notebook),
        "server_token": "server-token",
    }

    assert parse_connection_token(payload, notebook) == "server-token"
    with pytest.raises(ProtocolError, match="connection response"):
        parse_connection_token({**payload, "notebook": "other.py"}, notebook)
    with pytest.raises(ProtocolError, match="connection response"):
        parse_connection_token({**payload, "schema": True}, notebook)


def _show_payload(notebook: Path) -> dict[str, object]:
    return {
        "schema": 1,
        "notebook": str(notebook),
        "view": "dashboard",
        "generation": 1,
        "client_id": "browser-client-1234",
        "session_id": "s_123456",
        "preview_url": "http://localhost/preview/",
        "frame_selector": "iframe[data-browser-owned-selector]",
    }


def test_show_protocol_accepts_identity_results(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    active = parse_show_result(
        _show_payload(notebook),
        notebook,
        "dashboard",
    )
    assert active.client_id == "browser-client-1234"
    assert active.frame_selector == "iframe[data-browser-owned-selector]"
    assert active.preview_url == "http://localhost/preview/"


@pytest.mark.parametrize(
    "patch",
    [
        {"schema": True},
        {"generation": True},
        {"unexpected": True},
    ],
)
def test_show_protocol_rejects_invalid_results(
    tmp_path: Path,
    patch: dict[str, object],
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = {**_show_payload(notebook), **patch}

    with pytest.raises(ProtocolError, match="show response"):
        parse_show_result(payload, notebook, "dashboard")


@pytest.mark.parametrize(
    "field,value",
    [
        ("preview_url", None),
        ("preview_url", "https://"),
        ("preview_url", "http://localhost:invalid/"),
        ("preview_url", "http://localhost:65536/"),
        ("frame_selector", None),
        ("frame_selector", 7),
    ],
)
def test_show_protocol_requires_browser_automation_target(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = _show_payload(notebook)
    with pytest.raises(ProtocolError):
        parse_show_result({**payload, field: value}, notebook, "dashboard")
    del payload[field]
    with pytest.raises(ProtocolError):
        parse_show_result(payload, notebook, "dashboard")


def test_show_result_preserves_positional_identity_fields(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    result = ShowResult(
        notebook,
        "dashboard",
        2,
        "s_123456",
        "browser-client-1234",
        preview_url="http://localhost/preview/",
        frame_selector="iframe[data-test-preview]",
    )
    assert result.to_dict() == {
        **_show_payload(notebook),
        "generation": 2,
        "frame_selector": "iframe[data-test-preview]",
    }
