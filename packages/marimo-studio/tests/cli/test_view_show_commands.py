from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio.agent import ShowResult


def test_view_show_returns_the_shared_result(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)

    async def show(notebook, name, connection):
        assert notebook == notebook_path.resolve()
        assert name == "dashboard"
        return ShowResult(
            notebook=notebook,
            view=name,
            generation=2,
            session_id="s_123456",
            client_id=connection.browser_client,
        )

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.show_view",
        show,
    )
    result = CliRunner().invoke(
        cli,
        [
            "view",
            "show",
            "dashboard",
            "--target",
            str(notebook_path),
            "--json",
        ],
        env={
            "MARIMO_STUDIO_SERVER_URL": "http://localhost:2718",
            "MARIMO_STUDIO_BROWSER_CLIENT": "browser-client-1234",
            "MARIMO_STUDIO_ACCESS_TOKEN": "access-token",
        },
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "schema": 1,
        "notebook": str(notebook_path),
        "view": "dashboard",
        "generation": 2,
        "session_id": "s_123456",
        "client_id": "browser-client-1234",
    }


def test_view_show_requires_a_server(notebook_path: Path) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        ["view", "show", "dashboard", "--target", str(notebook_path)],
    )

    assert result.exit_code == 2
    assert "--server" in result.output


@pytest.mark.parametrize(
    ("arguments", "environment"),
    (
        (["--server", "http://studio.example.test:2718"], {}),
        ([], {"MARIMO_STUDIO_SERVER_URL": "http://studio.example.test:2718"}),
    ),
)
def test_view_show_requires_https_for_remote_server_inputs(
    notebook_path: Path,
    arguments: list[str],
    environment: dict[str, str],
) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "show",
            "dashboard",
            "--target",
            str(notebook_path),
            *arguments,
        ],
        env=environment,
    )

    assert result.exit_code == 2
    assert "--server" in result.output
    assert "must use https" in result.output


def test_view_show_flags_override_connection_environment(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    captured: dict[str, str] = {}

    def connection(server_url: str, *, access_token: str, browser_client: str):
        captured.update(
            server_url=server_url,
            access_token=access_token,
            browser_client=browser_client,
        )
        raise RuntimeError("connection captured")

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.studio_server_connection",
        connection,
    )
    result = CliRunner().invoke(
        cli,
        [
            "view",
            "show",
            "dashboard",
            "--target",
            str(notebook_path),
            "--server",
            "https://explicit.example.test:2718",
            "--browser-client",
            "explicit-client",
        ],
        env={
            "MARIMO_STUDIO_SERVER_URL": "https://environment.example.test:2718",
            "MARIMO_STUDIO_BROWSER_CLIENT": "environment-client",
            "MARIMO_STUDIO_ACCESS_TOKEN": "access-token",
        },
    )

    assert isinstance(result.exception, RuntimeError)
    assert captured == {
        "server_url": "https://explicit.example.test:2718",
        "access_token": "access-token",
        "browser_client": "explicit-client",
    }
