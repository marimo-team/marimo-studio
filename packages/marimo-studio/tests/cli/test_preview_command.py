from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli


@pytest.mark.parametrize("json_output", [False, True])
def test_preview_prints_only_the_url(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool
) -> None:
    url = (
        "https://studio.example/base/dashboard/?runtime=wasm&marimo_studio_revision="
        + "a" * 64
    )

    async def preview(notebook, view, connection, *, runtime, exact):
        assert notebook == notebook_path
        assert view == "dashboard"
        assert connection.server_url == "https://studio.example/base"
        assert connection.auth_token == "secret"
        assert runtime == "wasm"
        assert exact is True
        return url

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.preview_url", preview
    )
    arguments = [
        "view",
        "preview",
        "dashboard",
        "--target",
        str(notebook_path),
        "--server",
        "https://studio.example/base",
        "--runtime",
        "wasm",
        "--exact",
    ]
    if json_output:
        arguments.append("--json")
    result = CliRunner().invoke(
        cli, arguments, env={"MARIMO_STUDIO_ACCESS_TOKEN": "secret"}
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == (json.dumps(url) if json_output else url) + "\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "options, expected",
    [
        (["--server", "http://localhost:2718"], "--runtime"),
        (["--runtime", "wasm"], "--server"),
        (["--runtime", "wasm", "--server", "ftp://localhost"], "--server"),
        (["--runtime", "unknown", "--server", "http://localhost:2718"], "--runtime"),
    ],
)
def test_preview_rejects_invalid_connection_options(options, expected) -> None:
    result = CliRunner().invoke(
        cli,
        ["view", "preview", "dashboard", *options],
        env={"MARIMO_STUDIO_SERVER_URL": ""},
    )
    assert result.exit_code == 2
    assert expected in result.output


def test_preview_main_preserves_json_stdout(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sys

    from marimo_studio._cli import main

    url = "http://localhost:2718/dashboard/?runtime=wasm&marimo_studio_unframed=1"

    async def preview(*_args, **_kwargs):
        return url

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.preview_url", preview
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "marimo-studio",
            "view",
            "preview",
            "dashboard",
            "--target",
            str(notebook_path),
            "--server",
            "http://localhost:2718",
            "--runtime",
            "wasm",
            "--json",
        ],
    )
    main()
    captured = capsys.readouterr()
    assert captured.out == json.dumps(url) + "\n"
    assert captured.err == ""
