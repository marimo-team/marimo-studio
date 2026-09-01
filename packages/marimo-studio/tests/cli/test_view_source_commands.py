from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click import unstyle
from click.testing import CliRunner

import marimo_studio._views.sources as sources_module
from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio._views.records import ViewDocument
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.view_owners import view_owner_path
from marimo_studio.errors import (
    ConfigurationError,
    SourceConflictError,
    SourceEncodingError,
    SourceNotFoundError,
    SourceTooLargeError,
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.view_providers import SourceDocument, ViewProject

from ..helpers import replace_app_shell


def _owner_arguments(document: dict[str, object]) -> list[str]:
    return [
        "--catalog-generation",
        str(document["catalog_generation"]),
        "--view-generation",
        str(document["view_generation"]),
    ]


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
            "--json",
        ],
    )

    output = unstyle(result.output)
    assert result.exit_code == 0, result.output
    assert machine.exit_code == 0, machine.output
    assert "build unbuilt" in output
    assert "documents" in output
    assert "diagnostics" in output
    assert "index.html" in output
    payload = json.loads(machine.stdout)
    assert payload["freshness"] == "unbuilt"
    assert payload["build"] is None


def test_view_inspect_human_output_includes_repair_and_retained_build(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
    built = CliRunner().invoke(
        cli,
        ["view", "build", "dashboard", "--target", str(notebook_path)],
    )
    assert built.exit_code == 0, built.output
    document = setup.root / "index.html"
    document.write_text(
        replace_app_shell(
            document.read_text(encoding="utf-8"),
            '<marimo-cell name="missing"></marimo-cell>',
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["view", "inspect", "dashboard", "--target", str(notebook_path)],
    )

    output = unstyle(result.output)
    assert result.exit_code == 0, result.output
    assert "repair" in output
    assert "Name the notebook cell" in output
    assert "published development sha256:" in output


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
            "--json",
        ],
    )

    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    studio = load_studio(notebook_path)
    assert document["catalog_generation"] == studio.catalog_generation
    assert document["view_generation"] == studio.view_generations["dashboard"]
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
            *_owner_arguments(document),
            "--from",
            "-",
            "--json",
        ],
        input=content,
    )

    assert written.exit_code == 0, written.output
    updated = json.loads(written.stdout)
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
            *_owner_arguments(document),
            "--from",
            "-",
        ],
        input=document["content"],
    )
    assert stale.exit_code != 0
    assert isinstance(stale.exception, SourceConflictError)


def test_view_write_rejects_an_identical_recreated_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepare_view(notebook_path)
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
            "--json",
        ],
    )
    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    retired = setup.root.with_name("retired-dashboard")
    setup.root.rename(retired)
    shutil.copytree(retired, setup.root)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.provider_bootstrap_required",
        lambda _target: pytest.fail("stale source owner reached provider bootstrap"),
    )

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
            *_owner_arguments(document),
            "--from",
            "-",
        ],
        input=document["content"].replace("Dashboard", "Stale write"),
    )

    assert isinstance(written.exception, ViewGenerationConflictError)
    assert (
        setup.root.joinpath("index.html").read_text(encoding="utf-8")
        == document["content"]
    )


def test_view_manifest_read_rejects_a_replacement_during_owner_capture(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepare_view(notebook_path)
    retired = setup.root.with_name("retired-dashboard")
    read_manifest = sources_module._read_view_manifest_locked

    def read_then_replace(
        studio: StudioDefinition,
        view_name: str,
    ) -> ViewDocument:
        document = read_manifest(studio, view_name)
        setup.root.rename(retired)
        shutil.copytree(retired, setup.root)
        return document

    monkeypatch.setattr(
        sources_module,
        "_read_view_manifest_locked",
        read_then_replace,
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert isinstance(result.exception, ViewGenerationConflictError)


def test_view_source_read_rejects_a_replacement_during_owner_capture(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepare_view(notebook_path)
    retired = setup.root.with_name("retired-dashboard")
    read_source = sources_module._read

    def read_then_replace(
        studio: StudioWorkspace,
        project: ViewProject,
        spec: SourceDocument,
    ) -> ViewDocument:
        document = read_source(studio, project, spec)
        setup.root.rename(retired)
        shutil.copytree(retired, setup.root)
        return document

    monkeypatch.setattr(sources_module, "_read", read_then_replace)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "index.html",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert isinstance(result.exception, ViewGenerationConflictError)


def test_view_manifest_write_rechecks_a_replacement_after_admission(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepare_view(notebook_path)
    runner = CliRunner()
    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )
    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    retired = setup.root.with_name("retired-dashboard")
    reload_owner = sources_module._reload_source_owner
    reloads = 0

    def reload_then_replace(
        studio: StudioDefinition,
        view_name: str,
        *,
        expected_catalog_generation: str | None,
        expected_generation: str | None,
    ) -> StudioDefinition:
        nonlocal reloads
        current = reload_owner(
            studio,
            view_name,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )
        reloads += 1
        if reloads == 2:
            setup.root.rename(retired)
            shutil.copytree(retired, setup.root)
        return current

    monkeypatch.setattr(sources_module, "_reload_source_owner", reload_then_replace)

    written = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            *_owner_arguments(document),
            "--from",
            "-",
        ],
        input=document["content"] + '\n[options]\nmode = "compact"\n',
    )

    assert isinstance(written.exception, ViewGenerationConflictError)
    assert (
        setup.root.joinpath("view.toml").read_text(encoding="utf-8")
        == document["content"]
    )


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--catalog-generation", "0" * 63),
        ("--view-generation", "A" * 64),
    ],
)
def test_view_write_rejects_malformed_owner_generations_before_admission(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    value: str,
) -> None:
    prepare_view(notebook_path)
    arguments: dict[str, str] = {
        "--catalog-generation": "0" * 64,
        "--view-generation": "1" * 64,
    }
    arguments[flag] = value

    def fail_admission(
        _target: str | Path,
        _view_name: str,
        *,
        expected_catalog_generation: str | None,
        expected_generation: str | None,
    ) -> None:
        _ = expected_catalog_generation, expected_generation
        pytest.fail("invalid generation reached admission")

    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.admit_source_owner",
        fail_admission,
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "index.html",
            "--target",
            str(notebook_path),
            "--expected-revision",
            "sha256:revision",
            "--catalog-generation",
            arguments["--catalog-generation"],
            "--view-generation",
            arguments["--view-generation"],
            "--from",
            "-",
        ],
    )

    assert result.exit_code == 2
    assert "64-character lowercase hexadecimal string" in result.output


def test_view_write_reports_a_missing_view_as_an_owner_conflict(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "write",
            "missing",
            "index.html",
            "--target",
            str(notebook_path),
            "--expected-revision",
            "sha256:revision",
            "--catalog-generation",
            studio.catalog_generation,
            "--view-generation",
            "0" * 64,
            "--from",
            "-",
        ],
    )

    assert isinstance(result.exception, ViewGenerationConflictError)
    assert result.exception.current_generation is None


def test_view_manifest_read_and_write_repair_a_malformed_manifest_without_bootstrap(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepare_view(notebook_path)
    manifest = setup.root / "view.toml"
    repaired = manifest.read_text(encoding="utf-8")
    malformed = "schema = [\n"
    manifest.write_text(malformed, encoding="utf-8")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.provider_bootstrap_required",
        lambda _target: pytest.fail("view.toml triggered provider bootstrap"),
    )
    runner = CliRunner()

    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    assert document["content"] == malformed
    written = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            *_owner_arguments(document),
            "--from",
            "-",
            "--json",
        ],
        input=repaired,
    )

    assert written.exit_code == 0, written.output
    assert json.loads(written.stdout)["content"] == repaired


def test_view_manifest_repair_rejects_a_changed_sibling_catalog(
    notebook_path: Path,
) -> None:
    dashboard = prepare_view(notebook_path)
    executive = prepare_view(notebook_path, "executive")
    manifest = dashboard.root / "view.toml"
    repaired = manifest.read_text(encoding="utf-8")
    malformed = "schema = [\n"
    manifest.write_text(malformed, encoding="utf-8")
    runner = CliRunner()
    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )
    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    retired = executive.root.with_name("retired-executive")
    executive.root.rename(retired)
    shutil.copytree(retired, executive.root)

    written = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            *_owner_arguments(document),
            "--from",
            "-",
        ],
        input=repaired,
    )

    assert isinstance(written.exception, WorkspaceGenerationConflictError)
    assert manifest.read_text(encoding="utf-8") == malformed


def test_view_manifest_repair_rejects_a_new_manifestless_sibling(
    notebook_path: Path,
) -> None:
    dashboard = prepare_view(notebook_path)
    manifest = dashboard.root / "view.toml"
    repaired = manifest.read_text(encoding="utf-8")
    malformed = "schema = [\n"
    manifest.write_text(malformed, encoding="utf-8")
    runner = CliRunner()
    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )
    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    dashboard.root.parent.joinpath("incoming").mkdir()

    written = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            *_owner_arguments(document),
            "--from",
            "-",
        ],
        input=repaired,
    )

    assert isinstance(written.exception, WorkspaceGenerationConflictError)
    assert manifest.read_text(encoding="utf-8") == malformed


def test_view_manifest_write_keeps_an_external_provider_independent(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = prepare_view(notebook_path)
    manifest = setup.root / "view.toml"
    external = manifest.read_text(encoding="utf-8").replace(
        'provider = "marimo-studio/vanilla"',
        'provider = "example-suite/report"',
    )
    manifest.write_text(external, encoding="utf-8")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.provider_bootstrap_required",
        lambda _target: pytest.fail("view.toml triggered provider bootstrap"),
    )
    runner = CliRunner()
    loaded = runner.invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert loaded.exit_code == 0, loaded.output
    document = json.loads(loaded.stdout)
    updated = external + '\n[options]\nmode = "compact"\n'
    written = runner.invoke(
        cli,
        [
            "view",
            "write",
            "dashboard",
            "view.toml",
            "--target",
            str(notebook_path),
            "--expected-revision",
            document["revision"],
            *_owner_arguments(document),
            "--from",
            "-",
            "--json",
        ],
        input=updated,
    )

    assert written.exit_code == 0, written.output
    assert json.loads(written.stdout)["content"] == updated


def test_view_read_rejects_an_invalid_path_before_provider_bootstrap(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.provider_bootstrap_required",
        lambda _target: pytest.fail("invalid path triggered provider bootstrap"),
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "read",
            "dashboard",
            "../view.toml",
            "--target",
            str(notebook_path),
        ],
    )

    assert isinstance(result.exception, SourceNotFoundError)


def test_view_manifest_read_does_not_adopt_a_reserved_view_name(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    reserved = studio.view_root / "api"
    reserved.mkdir()
    reserved.joinpath("view.toml").write_text(
        'schema = 1\nprovider = "marimo-studio/vanilla"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "view",
            "read",
            "api",
            "view.toml",
            "--target",
            str(notebook_path),
            "--json",
        ],
    )

    assert isinstance(result.exception, SourceNotFoundError)
    assert not view_owner_path(studio.view_root, "api").exists()
    shutil.rmtree(reserved)
    assert set(load_studio(notebook_path).views) == {"dashboard"}


@pytest.mark.parametrize("command", ("read", "write"))
def test_view_manifest_commands_admit_the_notebook_before_source_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    target = tmp_path / "analysis.txt"
    target.write_text("import marimo\n", encoding="utf-8")
    monkeypatch.setattr(
        "marimo_studio._cli.commands.view_source.read_source_input",
        lambda _source: pytest.fail("invalid target consumed source input"),
    )
    arguments = ["view", command, "dashboard", "view.toml"]
    if command == "write":
        arguments.extend(
            [
                "--expected-revision",
                "revision",
                "--catalog-generation",
                "0" * 64,
                "--view-generation",
                "0" * 64,
                "--from",
                "-",
            ]
        )

    result = CliRunner().invoke(
        cli,
        [*arguments, "--target", str(target)],
    )

    assert isinstance(result.exception, ConfigurationError)


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
            "--json",
        ],
    )
    document = json.loads(loaded.stdout)
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
        document["revision"],
        *_owner_arguments(document),
        "--from",
    ]
    too_large = runner.invoke(cli, [*arguments, str(oversized)])
    invalid_text = runner.invoke(cli, [*arguments, str(invalid)])

    assert isinstance(too_large.exception, SourceTooLargeError)
    assert isinstance(invalid_text.exception, SourceEncodingError)
