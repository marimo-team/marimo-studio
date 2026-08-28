from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.agent import ViewActivationResult
from marimo_studio.errors import (
    SourceConflictError,
    SourceEncodingError,
    SourceTooLargeError,
    ViewExistsError,
)
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..provider_test_support import EntryPointStub, ProviderStub, candidate
from .commands_test_support import (
    _passthrough_uv,
    _run_cli,
)


def test_provider_doctor_renders_finalized_registration_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = ProviderStub("example/malformed", "malformed")
    healthy = ProviderStub("example/healthy", "healthy")
    registry = ProviderRegistry(
        (
            ProviderCandidate(
                registration="INVALID REGISTRATION",
                distribution="broken-package",
                version="1.0.0",
                entry_point=cast(Any, EntryPointStub(malformed)),
            ),
            candidate("healthy", healthy),
        )
    )
    monkeypatch.setattr(
        "marimo_studio._authoring.workspace.provider_registry",
        lambda: registry,
    )

    human = CliRunner().invoke(cli, ["doctor"])
    result = CliRunner().invoke(cli, ["doctor", "--format", "json"])

    assert human.exit_code == 0, human.output
    human_output = unstyle(human.output)
    assert "distribution test-healthy" in human_output
    assert "registration healthy" in human_output
    assert "installed 1.0.0" in human_output
    assert result.exit_code == 0, result.output
    records = {
        item["registration"]: item for item in json.loads(result.output)["providers"]
    }
    assert records["INVALID REGISTRATION"]["key"] is None
    assert records["INVALID REGISTRATION"]["loaded"] is False
    assert "entry-point identity is invalid" in records["INVALID REGISTRATION"]["error"]
    assert records["healthy"]["loaded"] is True
    assert records["healthy"]["starters"] == ["test-healthy/healthy:healthy"]


def test_provider_doctor_keeps_the_derived_key_for_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ImportFailure(EntryPointStub):
        def load(self) -> object:
            raise ImportError("import failed")

    imported = ProviderStub("example/import", "default")
    import_registry = ProviderRegistry(
        (
            ProviderCandidate(
                registration="report",
                distribution="import-package",
                version="1.0.0",
                entry_point=cast(Any, ImportFailure(imported)),
            ),
        )
    )
    monkeypatch.setattr(
        "marimo_studio._authoring.workspace.provider_registry",
        lambda: import_registry,
    )

    result = CliRunner().invoke(
        cli,
        ["doctor", "import-package/report", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    records = json.loads(result.output)["providers"]
    assert {record["key"] for record in records} == {"import-package/report"}
    assert all(record["loaded"] is False for record in records)
    assert all("import failed" in record["error"] for record in records)


def test_view_create_bootstraps_lists_and_checks_named_views(
    notebook_path: Path,
) -> None:
    runner = CliRunner()

    created = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )
    added = runner.invoke(
        cli,
        [
            "view",
            "create",
            "executive",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )
    overview = runner.invoke(
        cli,
        ["status", "--target", str(notebook_path), "--format", "json"],
    )
    checked = runner.invoke(
        cli,
        [
            "validate",
            "executive",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )

    assert created.exit_code == 0, created.output
    assert added.exit_code == 0, added.output
    assert overview.exit_code == 0, overview.output
    assert checked.exit_code == 0, checked.output
    assert json.loads(created.output)["view"] == "dashboard"
    assert Path(json.loads(created.output)["root"]) == (
        notebook_path.parent / "__marimo__" / "studio" / "analysis" / "dashboard"
    )
    assert json.loads(added.output)["view"] == "executive"
    overview_payload = json.loads(overview.output)
    assert overview_payload["schema"] == 2
    assert [item["name"] for item in overview_payload["views"]] == [
        "dashboard",
        "executive",
    ]
    payload = json.loads(checked.output)
    assert payload["ok"] is True
    assert payload["view"] == "executive"
    assert any(
        check["name"] == "view:executive"
        for check in payload["evidence"]["static"]["checks"]
    )


def test_view_create_dry_run_matches_the_live_document_catalog_without_writing(
    notebook_path: Path,
) -> None:
    original = notebook_path.read_bytes()
    runner = CliRunner()

    preview = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert preview.exit_code == 0, preview.output
    preview_payload = json.loads(preview.output)
    assert preview_payload["dry_run"] is True
    assert preview_payload["view"] == "dashboard"
    assert preview_payload["schema"] == 2
    assert preview_payload["created"]
    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()

    created = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )

    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.output)
    assert preview_payload["documents"] == created_payload["documents"]
    assert [Path(path).name for path in created_payload["documents"]] == [
        "view.toml",
        "index.html",
        "AGENTS.md",
    ]


def test_view_create_rejects_an_existing_name_during_dry_run(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, ViewExistsError)


def test_human_output_uses_color_and_json_remains_machine_readable(
    notebook_path: Path,
) -> None:
    runner = CliRunner()
    human = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
        ],
        color=True,
    )
    machine = runner.invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--dry-run",
            "--format",
            "json",
        ],
        color=True,
    )

    assert human.exit_code == 0, human.output
    assert "\x1b[" in human.output
    human_output = unstyle(human.output)
    assert "Would create view dashboard" in human_output
    assert human_output.count(f"update {notebook_path}") == 1
    assert "\x1b[" not in machine.output
    assert json.loads(machine.output)["view"] == "dashboard"


def test_starter_human_output_reports_unavailable_recovery_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo_studio._views.catalog import get_starter
    from marimo_studio.view_providers import ProviderAvailability

    starter = replace(
        get_starter("marimo-studio/react:default"),
        availability=ProviderAvailability(
            False,
            reason="deno-package-missing",
            action="pip install 'marimo-studio[deno]'",
        ),
    )

    async def records():
        return (starter,)

    monkeypatch.setattr(
        "marimo_studio._cli.commands.starters.installed_starters",
        records,
    )

    result = CliRunner().invoke(cli, ["starters"])

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "unavailable" in output
    assert "deno-package-missing" in output
    assert output.count("pip install 'marimo-studio[deno]'") == 1


def test_starter_list_separates_human_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo_studio._views.catalog import get_starter
    from marimo_studio.view_providers import ProviderAvailability

    base = replace(
        get_starter("marimo-studio/vanilla:default"),
        availability=ProviderAvailability(True),
    )
    first = replace(
        base,
        id="example/first:default",
        summary="First starter.",
        provider="example/first",
    )
    second = replace(
        base,
        id="example/second:default",
        summary="Second starter.",
        provider="example/second",
    )

    async def records():
        return (first, second)

    monkeypatch.setattr(
        "marimo_studio._cli.commands.starters.installed_starters",
        records,
    )

    result = CliRunner().invoke(cli, ["starters"])

    assert result.exit_code == 0, result.output
    assert unstyle(result.output).splitlines() == [
        "available example/first:default",
        "  First starter.",
        "  provider example/first",
        "",
        "available example/second:default",
        "  Second starter.",
        "  provider example/second",
    ]


@pytest.mark.native_process
def test_new_command_errors_emit_the_complete_diagnostic_command(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "view",
        "build",
        "dashboard",
        "--target",
        str(tmp_path / "missing.py"),
        "--diagnostics",
        "jsonl",
    )

    assert result.returncode == 3, result.stderr
    event = json.loads(result.stderr)
    assert event["event"] == "diagnostic"
    assert event["command"] == "view build"


def test_view_create_reports_the_editor_command(notebook_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        ["view", "create", "dashboard", "--target", str(notebook_path)],
    )

    assert result.exit_code == 0, result.output
    arguments = ["marimo", "edit", str(notebook_path), "--sandbox"]
    expected = (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )
    assert expected in unstyle(result.stderr)


def test_view_inspect_human_output_renders_the_provider_project_catalog(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        ["view", "inspect", "dashboard", "--target", str(notebook_path)],
    )
    machine = CliRunner().invoke(
        cli,
        [
            "view",
            "inspect",
            "dashboard",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )

    output = unstyle(result.output)
    assert result.exit_code == 0, result.output
    assert machine.exit_code == 0, machine.output
    assert "build unbuilt" in output
    assert "documents" in output
    assert "diagnostics" in output
    assert "index.html" in output
    payload = json.loads(machine.output)
    assert payload["freshness"] == "unbuilt"
    assert payload["publication"] is None


def test_view_read_and_write_share_revision_aware_source_contract(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    runner = CliRunner()
    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "index.html",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )

    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.output)
    content = document["content"].replace("Dashboard", "CLI dashboard")
    written = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "index.html",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            "--from",
            "-",
            "--format",
            "json",
        ],
        input=content,
    )

    assert written.exit_code == 0, written.output
    updated = json.loads(written.output)
    assert updated["revision"] != document["revision"]
    assert "CLI dashboard" in updated["content"]
    stale = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "index.html",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            "--from",
            "-",
        ],
        input=document["content"],
    )
    assert stale.exit_code != 0
    assert isinstance(stale.exception, SourceConflictError)


def test_view_write_bounds_and_decodes_replacement_source(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    runner = CliRunner()
    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "index.html",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
    )
    revision = json.loads(loaded.output)["revision"]
    monkeypatch.setattr("marimo_studio._cli.input.SOURCE_DOCUMENT_MAX_BYTES", 4)
    oversized = tmp_path / "oversized.html"
    oversized.write_bytes(b"12345")
    invalid = tmp_path / "invalid.html"
    invalid.write_bytes(b"\xff")

    arguments = [
        "view",
        "write",
        "dashboard",
        "index.html",
        "--target",
        str(notebook_path),
        "--expected-revision",
        revision,
        "--from",
    ]
    too_large = runner.invoke(cli, [*arguments, str(oversized)])
    invalid_text = runner.invoke(cli, [*arguments, str(invalid)])

    assert isinstance(too_large.exception, SourceTooLargeError)
    assert isinstance(invalid_text.exception, SourceEncodingError)


def test_text_recovery_hints_respect_jsonl_diagnostics(
    notebook_path: Path,
) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "view",
            "create",
            "dashboard",
            "--target",
            str(notebook_path),
            "--diagnostics",
            "jsonl",
        ],
    )

    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert len(events) == 1
    event = events[0]
    arguments = ["marimo", "edit", str(notebook_path), "--sandbox"]
    expected = (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )
    assert event["code"] == "next-command"
    assert event["message"] == expected
    assert event["details"] == {"action": "edit"}


def test_view_activate_returns_the_shared_result(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)

    async def activate(notebook, name, connection):
        assert notebook == notebook_path.resolve()
        assert name == "dashboard"
        return ViewActivationResult(
            notebook=notebook,
            view=name,
            generation=2,
            session_id="s_123456",
            client_id=connection.browser_client,
        )

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_delivery.activate_view",
        activate,
    )
    result = CliRunner().invoke(
        cli,
        [
            "view",
            "activate",
            "dashboard",
            "--target",
            str(notebook_path),
            "--format",
            "json",
        ],
        env={
            "MARIMO_STUDIO_SERVER_URL": "http://localhost:2718",
            "MARIMO_STUDIO_BROWSER_CLIENT": "browser-client-1234",
            "MARIMO_STUDIO_ACCESS_TOKEN": "access-token",
        },
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "schema": 2,
        "notebook": str(notebook_path),
        "view": "dashboard",
        "generation": 2,
        "session_id": "s_123456",
        "client_id": "browser-client-1234",
    }


def test_view_activate_requires_a_server(notebook_path: Path) -> None:
    prepare_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        ["view", "activate", "dashboard", "--target", str(notebook_path)],
    )

    assert result.exit_code == 2
    assert "--server" in result.output


def test_view_activate_flags_override_connection_environment(
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
            "activate",
            "dashboard",
            "--target",
            str(notebook_path),
            "--server",
            "http://explicit:2718",
            "--browser-client",
            "explicit-client",
        ],
        env={
            "MARIMO_STUDIO_SERVER_URL": "http://environment:2718",
            "MARIMO_STUDIO_BROWSER_CLIENT": "environment-client",
            "MARIMO_STUDIO_ACCESS_TOKEN": "access-token",
        },
    )

    assert isinstance(result.exception, RuntimeError)
    assert captured == {
        "server_url": "http://explicit:2718",
        "access_token": "access-token",
        "browser_client": "explicit-client",
    }


def test_view_create_resolves_an_uninitialized_project_from_the_current_directory(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = notebook_path.parent / "pyproject.toml"
    pyproject.write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(notebook_path.parent)

    result = CliRunner().invoke(
        cli,
        ["view", "create", "dashboard", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["config"] == str(pyproject)
    assert load_studio(pyproject).default_view == "dashboard"


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
            "--format",
            "json",
        ],
    )
    assert by_ref.exit_code == 0, by_ref.output
    assert json.loads(by_ref.output)["cell"]["ref"] == payload["cell"]["ref"]


def test_view_remove_preserves_source_when_confirmation_is_declined(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    added = prepare_view(notebook_path, "executive")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_create._stdin_is_interactive",
        lambda: True,
    )

    result = CliRunner().invoke(
        cli,
        ["view", "remove", "executive", "--target", str(notebook_path)],
        input="n\n",
    )

    assert result.exit_code == 0
    assert added.root.is_dir()
    assert set(load_studio(notebook_path).views) == {"dashboard", "executive"}


def test_view_remove_reports_the_updated_view_inventory(notebook_path: Path) -> None:
    dashboard = prepare_view(notebook_path).root
    prepare_view(notebook_path, "executive")

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "remove",
            "dashboard",
            "--target",
            str(notebook_path),
            "--yes",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "default_view": "executive",
        "notebook": str(notebook_path),
        "schema": 1,
        "view": "dashboard",
        "views": ["executive"],
    }
    assert not dashboard.exists()


@pytest.mark.parametrize(
    "machine_args",
    (("--format", "json"), ("--diagnostics", "jsonl")),
    ids=("result-json", "diagnostics-jsonl"),
)
def test_view_remove_requires_yes_for_machine_output(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    machine_args: tuple[str, ...],
) -> None:
    prepare_view(notebook_path)
    added = prepare_view(notebook_path, "executive")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_create._stdin_is_interactive",
        lambda: True,
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "remove",
            "executive",
            "--target",
            str(notebook_path),
            *machine_args,
        ],
    )

    assert result.exit_code == 2
    assert "Pass --yes" in result.output
    assert added.root.is_dir()


@pytest.mark.native_process
def test_view_remove_requires_yes_for_noninteractive_use(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    prepare_view(notebook_path)
    added = prepare_view(notebook_path, "executive")

    result = _run_cli(
        runtime_assets,
        "view",
        "remove",
        "executive",
        "--target",
        str(notebook_path),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Pass --yes" in result.stderr
    assert added.root.is_dir()


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
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cells"][1]["runtime"]["status"] == "idle"
    assert payload["cells"][1]["runtime"]["outputs"][-1]["mimetype"] == "text/html"
    assert payload["runtime"]["values"] == {"doubled": 4, "x": 2}


@pytest.mark.skipif(os.name == "nt", reason="The re-entry probe uses a POSIX shim")
@pytest.mark.native_process
@pytest.mark.parametrize(
    "diagnostic_args",
    [(), ("--diagnostics", "jsonl")],
    ids=("text", "jsonl"),
)
def test_cli_runtime_inspection_preserves_json_across_environment_reentry(
    notebook_path: Path,
    runtime_assets: Path,
    diagnostic_args: tuple[str, ...],
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
        "--format",
        "json",
        *diagnostic_args,
        bootstrapped=False,
        environment={"PATH": f"{root}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["runtime"]["values"] == {"doubled": 4, "x": 2}
    assert "forged_result" in result.stderr
    assert "forged-uv-error" in result.stderr
    if diagnostic_args:
        events = [json.loads(line) for line in result.stderr.splitlines()]
        assert all(event["event"] == "diagnostic" for event in events)
        assert all(event["code"] == "process-output" for event in events)
