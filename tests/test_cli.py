from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner

import marimo_studio.cli as cli_module
from marimo_studio._workspace import ensure_view, load_studio
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio.cli import cli, main


def _run_cli(
    runtime_assets: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    script = """\
from pathlib import Path
import sys

import marimo_studio._assets as assets

runtime_assets = Path(sys.argv[1])
assets.runtime_assets_path = lambda: runtime_assets
from marimo_studio.cli import main

sys.argv = ["marimo-studio", *sys.argv[2:]]
main()
"""
    return subprocess.run(
        [sys.executable, "-c", script, str(runtime_assets), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_view_add_bootstraps_lists_and_checks_named_views(
    notebook_path: Path,
) -> None:
    runner = CliRunner()

    created = runner.invoke(
        cli,
        ["view", "add", "dashboard", str(notebook_path), "--format", "json"],
    )
    added = runner.invoke(
        cli,
        ["view", "add", "executive", str(notebook_path), "--format", "json"],
    )
    listed = runner.invoke(
        cli,
        ["view", "list", str(notebook_path), "--format", "json"],
    )
    checked = runner.invoke(
        cli,
        ["check", str(notebook_path), "--view", "executive", "--format", "json"],
    )

    assert created.exit_code == 0, created.output
    assert added.exit_code == 0, added.output
    assert listed.exit_code == 0, listed.output
    assert checked.exit_code == 0, checked.output
    assert json.loads(created.output)["view"] == "dashboard"
    assert "/__marimo__/studio/analysis/dashboard" in json.loads(created.output)["root"]
    assert json.loads(added.output)["view"] == "executive"
    assert [item["name"] for item in json.loads(listed.output)["views"]] == [
        "dashboard",
        "executive",
    ]
    payload = json.loads(checked.output)
    assert payload["ok"] is True
    assert payload["view"] == "executive"
    assert any(check["name"] == "view:executive" for check in payload["checks"])


def test_view_add_rejects_a_missing_explicit_target(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    missing = tmp_path / "missing.py"

    result = _run_cli(
        runtime_assets,
        "view",
        "add",
        "executive",
        str(missing),
    )

    assert result.returncode == 3
    assert result.stdout == ""
    assert f"Notebook does not exist: {missing}" in result.stderr


def test_view_add_dry_run_reports_changes_without_writing(
    notebook_path: Path,
) -> None:
    original = notebook_path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "add",
            "dashboard",
            str(notebook_path),
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["view"] == "dashboard"
    assert payload["created"]
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_help_presents_direct_launch_as_the_root_command() -> None:
    root = CliRunner().invoke(cli, ["--help"], prog_name="marimo-studio")
    direct = CliRunner().invoke(
        cli,
        ["analysis.py", "--help"],
        prog_name="marimo-studio",
    )

    assert root.exit_code == 0
    assert root.output.startswith(
        "Usage:\n"
        "  marimo-studio [NOTEBOOK] [OPTIONS]\n"
        "  marimo-studio COMMAND [ARGS]...\n"
    )
    assert direct.exit_code == 0
    assert direct.output.startswith(
        "Usage: marimo-studio [NOTEBOOK] [OPTIONS] [-- MARIMO_ARGS]\n"
    )


def test_launch_validates_options_before_bootstrap(notebook_path: Path) -> None:
    original = notebook_path.read_bytes()
    runner = CliRunner()

    base_url = runner.invoke(
        cli,
        [str(notebook_path), "--base-url", "invalid"],
    )
    compact_port = runner.invoke(
        cli,
        [str(notebook_path), "--", "-p9000"],
    )

    assert base_url.exit_code == 2
    assert compact_port.exit_code == 2
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_cli_bind_updates_the_shared_cell_registry(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    runner = CliRunner()

    bound = runner.invoke(
        cli,
        [
            "bind",
            "summary",
            str(notebook_path),
            "--cell",
            "1",
            "--format",
            "json",
        ],
    )

    assert bound.exit_code == 0, bound.output
    payload = json.loads(bound.output)
    assert payload["alias"] == "summary"
    assert set(payload["cell"]) == {
        "index",
        "name",
        "ref",
        "runtime_id",
        "source",
    }
    assert str(load_studio(notebook_path).cells["summary"]) == payload["cell"]["ref"]


def test_cli_inspect_runtime_reports_mime_and_json_values(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "inspect",
        str(notebook_path),
        "--runtime",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cells"][1]["runtime"]["status"] == "idle"
    assert payload["cells"][1]["runtime"]["outputs"][-1]["mimetype"] == "text/html"
    assert payload["runtime"]["values"] == {"doubled": 4, "x": 2}


def test_check_emits_structured_diagnostics(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    ensure_view(notebook_path)

    result = _run_cli(
        runtime_assets,
        "check",
        str(notebook_path),
        "--format",
        "json",
        "--diagnostics",
        "jsonl",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert [event["code"] for event in events] == [
        check["name"] for check in payload["checks"]
    ]
    assert all(
        event["schema"] == 1
        and event["event"] == "diagnostic"
        and event["severity"] == "info"
        for event in events
    )


def test_main_structures_configuration_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(
        sys,
        "argv",
        ["marimo-studio", "check", str(missing), "--diagnostics", "jsonl"],
    )

    with pytest.raises(SystemExit) as raised:
        main()

    output = capsys.readouterr()
    event = json.loads(output.err)
    assert raised.value.code == 3
    assert output.out == ""
    assert event["code"] == "configuration-error"
    assert event["severity"] == "error"
    assert event["exit_code"] == 3


def test_direct_launch_starts_native_marimo_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path | None]] = []
    monkeypatch.setattr(
        cli_module,
        "environment_command",
        lambda _target, args: ["notebook-environment", *args],
    )
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs.get("cwd"))) or SimpleNamespace(returncode=0)
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            str(notebook_path),
            "--view",
            "dashboard",
            "--headless",
            "--port",
            "9123",
            "--base-url",
            "/proxy/token",
            "--",
            "--no-token",
        ],
    )

    assert result.exit_code == 0, result.output
    output = result.output.splitlines()
    assert len(output) == 2
    studio_url = urlsplit(output[0].removeprefix("Studio: ").strip())
    view_url = urlsplit(output[1].removeprefix("View:   ").strip())
    assert studio_url.hostname == "127.0.0.1"
    assert studio_url.port == 9123
    assert studio_url.path == "/proxy/token/studio/dashboard/"
    assert studio_url.query == ""
    assert view_url.path == "/proxy/token/dashboard/"
    assert view_url.query == ""
    assert len(calls) == 1
    command, cwd = calls[0]
    assert cwd == notebook_path.parent
    assert command[:4] == [
        "notebook-environment",
        "marimo",
        "edit",
        str(notebook_path),
    ]
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "9123"
    assert command[command.index("--base-url") + 1] == "/proxy/token"
    assert command[-3:] == ["--headless", "--no-sandbox", "--no-token"]
    assert load_studio(notebook_path).config_path == notebook_path


def test_direct_launch_opens_an_authenticated_studio_url(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    opened: list[str] = []
    monkeypatch.setattr(cli_module.secrets, "token_urlsafe", lambda _size: "secret")
    monkeypatch.setattr(cli_module, "_open_later", opened.append)
    monkeypatch.setattr(
        cli_module,
        "environment_command",
        lambda _target, args: ["notebook-environment", *args],
    )
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda command, **_kwargs: (
            calls.append(command) or SimpleNamespace(returncode=0)
        ),
    )

    result = CliRunner().invoke(
        cli,
        [str(notebook_path), "--port", "9124"],
    )

    assert result.exit_code == 0, result.output
    output = result.output.splitlines()
    assert len(output) == 2
    studio_url = output[0].removeprefix("Studio: ").strip()
    view_url = output[1].removeprefix("View:   ").strip()
    assert opened == [studio_url]
    assert urlsplit(studio_url).path == "/studio/dashboard/"
    assert urlsplit(view_url).path == "/dashboard/"
    assert parse_qs(urlsplit(studio_url).query) == {
        "access_token": ["secret"],
    }
    assert parse_qs(urlsplit(view_url).query) == {"access_token": ["secret"]}
    assert calls[0][-2:] == ["--token-password", "secret"]


def test_bare_launch_discovers_the_configured_notebook(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    calls: list[list[str]] = []
    monkeypatch.chdir(notebook_path.parent)
    monkeypatch.setattr(
        cli_module,
        "environment_command",
        lambda _target, args: ["notebook-environment", *args],
    )
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda command, **_kwargs: (
            calls.append(command) or SimpleNamespace(returncode=0)
        ),
    )

    result = CliRunner().invoke(cli, ["--headless"])

    assert result.exit_code == 0, result.output
    assert calls[0][1:4] == ["marimo", "edit", str(notebook_path)]


def test_direct_launch_converges_the_notebook_package_requirement(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        """\
# /// script
# requires-python = ">=3.11"
# dependencies = ["humanize>=4", "marimo-studio==1.2.3"]
#
# [tool.marimo-studio]
# default = "dashboard"
# cells = {}
# ///

"""
        + body,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_module,
        "environment_command",
        lambda _target, _args: ["true"],
    )
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda _command, **_kwargs: SimpleNamespace(returncode=0),
    )

    result = CliRunner().invoke(
        cli,
        [str(notebook_path), "--headless"],
    )
    document = read_notebook_metadata(notebook_path)

    assert result.exit_code == 0, result.output
    assert document is not None
    assert list(document["dependencies"]) == [
        "humanize>=4",
        "marimo-studio",
    ]
    assert notebook_path.read_text(encoding="utf-8").endswith(body)


def test_direct_launch_rejects_managed_options_after_separator(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        str(notebook_path),
        "--headless",
        "--",
        "--proxy",
        "http://example.test",
    )

    assert result.returncode == 2
    assert "Pass --proxy before `--`" in result.stderr
