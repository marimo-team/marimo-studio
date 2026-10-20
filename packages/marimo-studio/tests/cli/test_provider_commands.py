from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from click import unstyle
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..provider_test_support import EntryPointStub, ProviderStub, candidate


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
    result = CliRunner().invoke(
        cli,
        [
            "doctor",
            "--json",
        ],
    )

    assert human.exit_code == 0, human.output
    human_output = unstyle(human.output)
    assert "distribution test-healthy" in human_output
    assert "registration healthy" in human_output
    assert "installed 1.0.0" in human_output
    assert result.exit_code == 0, result.output
    records = {
        item["registration"]: item for item in json.loads(result.stdout)["providers"]
    }
    assert records["INVALID REGISTRATION"]["key"] is None
    assert records["INVALID REGISTRATION"]["loaded"] is False
    assert records["INVALID REGISTRATION"]["error"]
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
        [
            "doctor",
            "import-package/report",
            "--json",
        ],
    )

    assert result.exit_code == 1, result.output
    records = json.loads(result.stdout)["providers"]
    assert {record["key"] for record in records} == {"import-package/report"}
    assert all(record["loaded"] is False for record in records)
    assert all("import failed" in record["error"] for record in records)


def test_provider_doctor_renders_recovery_after_availability_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example/report", "default")
    provider.availability_error = RuntimeError("availability failed")
    registry = ProviderRegistry((candidate("report", provider),))
    monkeypatch.setattr(
        "marimo_studio._authoring.workspace.provider_registry",
        lambda: registry,
    )

    result = CliRunner().invoke(cli, ["doctor"])

    assert result.exit_code == 0, result.output
    output = unstyle(result.output)
    assert "RuntimeError: availability failed" in output
    assert any(line.strip().startswith("recover ") for line in output.splitlines())


def test_starter_human_output_reports_unavailable_recovery_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo_studio._views.catalog import get_starter
    from marimo_studio.view_providers import ProviderAvailability

    action = "Install marimo-studio[deno] in the Python environment that runs Studio."
    starter = replace(
        get_starter("marimo-studio/react:default"),
        availability=ProviderAvailability(
            False,
            reason="deno-package-missing",
            action=action,
        ),
    )

    async def records(_notebook):
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
    assert output.count(action) == 1


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

    async def records(_notebook):
        return (first, second)

    monkeypatch.setattr(
        "marimo_studio._cli.commands.starters.installed_starters",
        records,
    )

    result = CliRunner().invoke(cli, ["starters"])

    assert result.exit_code == 0, result.output
    first_record, second_record = unstyle(result.output).strip().split("\n\n")
    assert "example/first:default" in first_record
    assert "First starter." in first_record
    assert "example/second:default" in second_record
    assert "Second starter." in second_record


@pytest.mark.parametrize(
    "arguments",
    (["starters"], ["doctor", "marimo-studio/latex"]),
    ids=("starters", "doctor"),
)
def test_tool_availability_reports_a_target_with_invalid_metadata(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        "# /// script\n"
        '# dependencies = ["marimo"]\n'
        "#\n"
        "# [tool.pixi.dependencies]\n"
        "# tectonic =\n"
        "# ///\n"
        "import marimo\n"
        "app = marimo.App()\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, [*arguments, "--target", str(notebook)])

    assert isinstance(result.exception, ConfigurationError)
    assert "Notebook has invalid PEP 723 metadata" in str(result.exception)
