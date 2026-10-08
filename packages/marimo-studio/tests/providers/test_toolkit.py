"""Exercise the provider SDK helpers that built-in and installed providers share."""

from __future__ import annotations

import os
import threading
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._filesystem.budgets import FileBudget
from marimo_studio._processes.cancellation import provider_cancellation
from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessResult
from marimo_studio.view_providers import (
    ProviderCancellation,
    ProviderCommandError,
    ProviderError,
    SourceLocation,
    ViewProject,
    copy_inputs,
    probe_tool,
    project_files,
)
from marimo_studio.view_providers import _toolkit as toolkit

from ..provider_test_support import inspection, provider_build_request

posix_only = pytest.mark.skipif(os.name == "nt", reason="uses POSIX shell scripts")


def _project(root: Path, **options: str) -> ViewProject:
    root.mkdir(parents=True, exist_ok=True)
    return ViewProject("view", root, root / "view.toml", "test/provider", options)


def _tool(directory: Path, script: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / "tool"
    tool.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    tool.chmod(0o755)
    return tool


def test_project_files_lists_build_files_and_skips_studio_files(tmp_path: Path) -> None:
    project = _project(tmp_path / "view")
    for relative in (
        "index.html",
        "figures/logo.svg",
        "view.toml",
        "AGENTS.md",
        ".DS_Store",
        ".env",
        ".vite/cache.json",
        "dist/index.html",
    ):
        path = project.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    assert project_files(project, exclude={"dist"}) == (
        PurePosixPath("figures/logo.svg"),
        PurePosixPath("index.html"),
    )
    assert project_files(project, roots={"figures"}) == (
        PurePosixPath("figures/logo.svg"),
    )


def test_project_files_stop_at_the_project_input_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path / "view")
    for index in range(3):
        project.root.joinpath(f"{index}.html").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        toolkit,
        "BUILD_INPUT_BUDGET",
        FileBudget(max_files=2, max_file_bytes=1024, max_total_bytes=4096),
    )

    with pytest.raises(ProviderError, match="more than 2"):
        project_files(project)


def test_copy_inputs_copies_build_inputs_until_cancelled(tmp_path: Path) -> None:
    project = _project(tmp_path / "view")
    project.root.joinpath("index.html").write_text("page", encoding="utf-8")
    project.root.joinpath("view.toml").write_text("", encoding="utf-8")
    staging = tmp_path / "build" / "files"
    staging.mkdir(parents=True)
    request = provider_build_request(project, inspection(), staging)

    copy_inputs(request, tmp_path / "copy")
    request.cancellation.cancel()

    assert sorted(path.name for path in (tmp_path / "copy").iterdir()) == ["index.html"]
    with pytest.raises(ProviderCommandError, match="cancelled"):
        copy_inputs(request, tmp_path / "again")


@pytest.mark.parametrize(
    ("value", "message"),
    (("../outside.html", "relative POSIX path"), ("report.md", "must name a .html")),
)
def test_path_options_report_invalid_values_at_view_toml(
    tmp_path: Path,
    value: str,
    message: str,
) -> None:
    project = _project(tmp_path / "view", entrypoint=value)

    with pytest.raises(ProviderError, match=message) as raised:
        project.path_option("entrypoint", default="index.html", suffix=".html")

    assert raised.value.diagnostic.source == SourceLocation(
        PurePosixPath("view.toml"), 1, 1
    )


@posix_only
def test_probe_tool_names_a_version_command_that_fails(tmp_path: Path) -> None:
    tool = _tool(tmp_path / "bin", "echo 'tool 2.0' >&2; exit 3")

    availability = probe_tool((str(tool), "--version"), minimum="1.0", install="x")

    assert not availability.available
    assert availability.reason == "tool --version exited with status 3."


@posix_only
@pytest.mark.parametrize(
    ("output", "available", "version"),
    (
        ("tool 2.9.5 (stable)", True, "2.9.5"),
        ("tool 2.10.0", True, "2.10.0"),
        ("tool 2.9.4", False, "2.9.4"),
        ("unknown", False, None),
    ),
)
def test_probe_tool_compares_the_reported_version(
    tmp_path: Path,
    output: str,
    available: bool,
    version: str | None,
) -> None:
    tool = _tool(tmp_path / "bin", f'echo "{output}"')

    availability = probe_tool((str(tool), "--version"), minimum="2.9.5", install="x")

    assert (availability.available, availability.version) == (available, version)


def test_probe_tool_reports_a_missing_command(tmp_path: Path) -> None:
    availability = probe_tool(
        (str(tmp_path / "absent"), "--version"),
        minimum="1.0",
        install="Install the tool.",
    )

    assert not availability.available
    assert availability.action == "Install the tool."


@posix_only
def test_probe_tool_checks_again_after_the_executable_changes(tmp_path: Path) -> None:
    log = tmp_path / "calls"
    tool = _tool(tmp_path / "bin", f'echo call >> "{log}"\necho "tool 1.0.0"')

    for _ in range(2):
        assert probe_tool((str(tool),), minimum="1.0", install="x").available
    tool.write_text(f'#!/bin/sh\necho call >> "{log}"\necho "tool 1.1.0"\n')

    assert probe_tool((str(tool),), minimum="1.0", install="x").version == "1.1.0"
    assert log.read_text(encoding="utf-8").count("call") == 2


@posix_only
def test_a_failed_probe_is_checked_again(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.touch()
    tool = _tool(tmp_path / "bin", f'[ -f "{broken}" ] && exit 1\necho "tool 1.0.0"')

    assert not probe_tool((str(tool),), minimum="1.0", install="x").available
    broken.unlink()

    assert probe_tool((str(tool),), minimum="1.0", install="x").available


@posix_only
def test_a_cancelled_probe_is_not_remembered(tmp_path: Path) -> None:
    stall = tmp_path / "stall"
    stall.touch()
    tool = _tool(
        tmp_path / "bin", f'[ -f "{stall}" ] && /bin/sleep 30\necho "tool 1.0.0"'
    )
    cancellation = ProviderCancellation()
    threading.Timer(0.2, cancellation.cancel).start()

    with (
        provider_cancellation(cancellation),
        pytest.raises(ProviderCommandError, match="cancelled"),
    ):
        probe_tool((str(tool),), minimum="1.0", install="x")
    stall.unlink()

    assert probe_tool((str(tool),), minimum="1.0", install="x").available


@posix_only
def test_probe_tool_surfaces_process_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool(tmp_path / "bin", 'echo "tool 1.0.0"')

    class Supervisor:
        def run(self, *_args: object, **_kwargs: object) -> ProcessResult:
            raise ProcessCleanupError("The version check survived its owner")

    monkeypatch.setattr(toolkit, "ProcessSupervisor", Supervisor)

    with pytest.raises(ProcessCleanupError, match="survived"):
        probe_tool((str(tool),), minimum="1.0", install="x")
