from __future__ import annotations

import json
import os
import shlex
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio

from .commands_test_support import _passthrough_uv, _run_cli


def test_status_reports_the_exact_requirement_for_first_view_creation(
    notebook_path: Path,
) -> None:
    runner = CliRunner()
    human = runner.invoke(cli, ["status", "--target", str(notebook_path)])
    machine = runner.invoke(
        cli,
        ["status", "--target", str(notebook_path), "--json"],
    )
    requirement = f"marimo-studio=={version('marimo-studio')}"
    arguments = [
        "uvx",
        "--from",
        requirement,
        "marimo-studio",
        "view",
        "create",
        "dashboard",
        "--target",
        str(notebook_path),
    ]
    expected = (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )

    assert human.exit_code == 0, human.output
    assert expected in unstyle(human.stderr)
    assert machine.exit_code == 0, machine.output
    assert json.loads(machine.stdout)["launch_requirements"] == [requirement]


def test_status_human_output_includes_configuration_runtime_and_aliases(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    runner = CliRunner()
    bound = runner.invoke(
        cli,
        [
            "notebook",
            "bind",
            "summary",
            "--target",
            str(notebook_path),
            "--cell",
            "1",
        ],
    )
    assert bound.exit_code == 0, bound.output

    result = runner.invoke(cli, ["status", "--target", str(notebook_path)])

    output = unstyle(result.output)
    assert result.exit_code == 0, result.output
    assert f"config notebook {notebook_path}" in output
    assert "runtime server" in output
    assert "runtimes server" in output
    assert "aliases" in output
    assert "summary cell:" in output


def test_command_help_exposes_target_and_required_options() -> None:
    runner = CliRunner()

    create_help = runner.invoke(
        cli,
        ["view", "create", "--help"],
        prog_name="marimo-studio",
    )
    bind_help = runner.invoke(
        cli,
        ["notebook", "bind", "--help"],
        prog_name="marimo-studio",
    )

    assert "Usage: marimo-studio view create [OPTIONS] VIEW" in create_help.output
    assert "--target PATH" in create_help.output
    assert "Usage: marimo-studio notebook bind [OPTIONS] ALIAS" in bind_help.output
    assert "--cell TEXT" in bind_help.output


def test_root_help_launches_marimo_with_the_exact_studio_distribution() -> None:
    result = CliRunner().invoke(
        cli,
        ["--help"],
        prog_name="marimo-studio",
        terminal_width=120,
    )

    assert result.exit_code == 0, result.output
    assert (
        f"uvx --with marimo-studio=={version('marimo-studio')} "
        "marimo edit analysis.py --sandbox"
    ) in unstyle(result.output)
    assert "Default Vanilla authoring:" in unstyle(result.output)


@pytest.mark.parametrize(
    "arguments",
    (
        ["status", "--help"],
        ["view", "create", "--help"],
        ["view", "inspect", "--help"],
        ["view", "read", "--help"],
        ["view", "write", "--help"],
        ["view", "build", "--help"],
        ["view", "export", "--help"],
        ["validate", "--help"],
    ),
)
def test_provider_command_help_explains_saved_environment_bootstrap(
    arguments: list[str],
) -> None:
    result = CliRunner().invoke(cli, arguments, prog_name="marimo-studio")

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "target's saved views and Python metadata" in output
    assert "filesystem, environment, and network authority" in output


def test_cli_bind_updates_the_shared_cell_registry(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    runner = CliRunner()

    bound = runner.invoke(
        cli,
        [
            "notebook",
            "bind",
            "summary",
            "--target",
            str(notebook_path),
            "--cell",
            "1",
            "--json",
        ],
    )

    assert bound.exit_code == 0, bound.output
    payload = json.loads(bound.stdout)
    assert payload["alias"] == "summary"
    assert set(payload["cell"]) == {
        "index",
        "name",
        "ref",
        "runtime_id",
        "source",
    }
    assert str(load_studio(notebook_path).cells["summary"]) == payload["cell"]["ref"]

    by_ref = runner.invoke(
        cli,
        [
            "notebook",
            "bind",
            "summary-ref",
            "--target",
            str(notebook_path),
            "--cell",
            payload["cell"]["ref"],
            "--json",
        ],
    )
    assert by_ref.exit_code == 0, by_ref.output
    assert json.loads(by_ref.stdout)["cell"]["ref"] == payload["cell"]["ref"]


@pytest.mark.native_process
def test_cli_inspect_runtime_reports_mime_and_json_values(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "notebook",
        "inspect",
        "--target",
        str(notebook_path),
        "--runtime",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cells"][1]["runtime"]["status"] == "idle"
    assert payload["cells"][1]["runtime"]["outputs"][-1]["mimetype"] == "text/html"
    assert payload["runtime"]["values"] == {"doubled": 4, "x": 2}


@pytest.mark.skipif(os.name == "nt", reason="The re-entry probe uses a POSIX shim")
@pytest.mark.native_process
def test_cli_runtime_inspection_preserves_json_across_environment_reentry(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    root = notebook_path.parent
    (root / "pyproject.toml").write_text(
        '[project]\nname = "inspection-probe"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    _passthrough_uv(root, emit_process_output=True)

    result = _run_cli(
        runtime_assets,
        "notebook",
        "inspect",
        "--target",
        str(notebook_path),
        "--runtime",
        "--json",
        bootstrapped=False,
        environment={"PATH": f"{root}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["runtime"]["values"] == {"doubled": 4, "x": 2}
    assert "forged_result" in result.stderr
    assert "forged-uv-error" in result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert all(event["event"] == "diagnostic" for event in events)
    assert all(event["code"] == "process-output" for event in events)
