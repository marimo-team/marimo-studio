from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import marimo_studio._workspace.launch as launch_module
from marimo_studio._workspace.launch import (
    LaunchArgumentError,
    LaunchPlan,
    LaunchRequest,
    browser_auth,
    execute_launch,
    prepare_launch,
)


def test_prepare_launch_builds_native_marimo_command_and_urls(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launch_module,
        "environment_command",
        lambda _target, args: ["notebook-environment", *args],
    )

    plan = prepare_launch(
        LaunchRequest(
            notebook=notebook_path,
            view_name="dashboard",
            host="0.0.0.0",
            port=9123,
            open_browser=True,
            base_url="/proxy/token",
            marimo_args=(),
        ),
        token_factory=lambda _size: "secret",
    )

    studio_url = urlsplit(plan.studio_url)
    view_url = urlsplit(plan.view_url)
    assert studio_url.hostname == "127.0.0.1"
    assert studio_url.path == "/proxy/token/studio/dashboard/"
    assert view_url.path == "/proxy/token/dashboard/"
    assert parse_qs(studio_url.query) == {"access_token": ["secret"]}
    assert plan.working_directory == notebook_path.parent
    assert plan.command[:4] == (
        "notebook-environment",
        "marimo",
        "edit",
        str(notebook_path),
    )
    assert plan.command[plan.command.index("--host") + 1] == "0.0.0.0"
    assert plan.command[-2:] == ("--token-password", "secret")


@pytest.mark.parametrize("base_url", ["/", "/proxy/"])
def test_prepare_launch_rejects_native_invalid_base_urls_before_writing(
    base_url: str,
    notebook_path: Path,
) -> None:
    with pytest.raises(
        LaunchArgumentError,
        match="must not",
    ):
        prepare_launch(
            LaunchRequest(
                notebook=notebook_path,
                view_name="dashboard",
                host="127.0.0.1",
                port=8000,
                open_browser=False,
                base_url=base_url,
                marimo_args=(),
            )
        )

    assert not (notebook_path.parent / "__marimo__").exists()


@pytest.mark.parametrize("option", ["--sandbox", "--no-sandbox"])
def test_prepare_launch_rejects_environment_passthrough_before_writing(
    option: str,
    notebook_path: Path,
) -> None:
    with pytest.raises(
        LaunchArgumentError,
        match="Studio prepares the notebook environment",
    ):
        prepare_launch(
            LaunchRequest(
                notebook=notebook_path,
                view_name="dashboard",
                host="127.0.0.1",
                port=8000,
                open_browser=False,
                base_url="",
                marimo_args=(option,),
            )
        )

    assert not (notebook_path.parent / "__marimo__").exists()


def test_prepare_launch_rejects_proxy_with_an_actionable_error(
    notebook_path: Path,
) -> None:
    with pytest.raises(
        LaunchArgumentError,
        match="direct launcher does not support --proxy",
    ):
        prepare_launch(
            LaunchRequest(
                notebook=notebook_path,
                view_name="dashboard",
                host="127.0.0.1",
                port=8000,
                open_browser=False,
                base_url="",
                marimo_args=("--proxy", "http://example.test"),
            )
        )


@pytest.mark.parametrize(
    "args",
    [
        ("--token-password", "secret", "--no-token"),
        ("--no-token", "--token-password", "secret"),
    ],
)
def test_browser_auth_gives_an_explicit_password_precedence(
    args: tuple[str, ...],
) -> None:
    marimo_args, access_token = browser_auth(args, open_browser=True)

    assert marimo_args == args
    assert access_token == "secret"


def test_prepare_launch_rejects_conflicting_password_sources_before_writing(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("from-file\n", encoding="utf-8")

    with pytest.raises(
        LaunchArgumentError,
        match="Only one of --token-password",
    ):
        prepare_launch(
            LaunchRequest(
                notebook=notebook_path,
                view_name="dashboard",
                host="127.0.0.1",
                port=8000,
                open_browser=True,
                base_url="",
                marimo_args=(
                    "--token-password",
                    "direct",
                    "--token-password-file",
                    str(token_file),
                ),
            )
        )

    assert not (notebook_path.parent / "__marimo__").exists()


def test_prepare_launch_resolves_token_files_before_changing_process_directory(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation_directory = tmp_path / "caller"
    invocation_directory.mkdir()
    token_file = invocation_directory / "token.txt"
    token_file.write_text("from-file\n", encoding="utf-8")
    monkeypatch.chdir(invocation_directory)

    plan = prepare_launch(
        LaunchRequest(
            notebook=notebook_path,
            view_name="dashboard",
            host="127.0.0.1",
            port=8000,
            open_browser=True,
            base_url="",
            marimo_args=("--token-password-file", "token.txt"),
        )
    )

    option_index = plan.command.index("--token-password-file")
    assert plan.command[option_index + 1] == str(token_file)
    assert parse_qs(urlsplit(plan.studio_url).query) == {
        "access_token": ["from-file"],
    }


def test_prepare_launch_rejects_non_utf8_token_files_before_writing(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_bytes(b"\xff")

    with pytest.raises(LaunchArgumentError, match="not valid UTF-8"):
        prepare_launch(
            LaunchRequest(
                notebook=notebook_path,
                view_name="dashboard",
                host="127.0.0.1",
                port=8000,
                open_browser=True,
                base_url="",
                marimo_args=("--token-password-file", str(token_file)),
            )
        )

    assert not (notebook_path.parent / "__marimo__").exists()


def test_execute_launch_opens_the_studio_and_forwards_process_streams(
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    calls: list[tuple[list[str], dict[str, object]]] = []
    plan = LaunchPlan(
        studio_url="http://127.0.0.1:8000/studio/dashboard/",
        view_url="http://127.0.0.1:8000/dashboard/",
        command=("uv", "run", "marimo", "edit", "analysis.py"),
        working_directory=tmp_path,
        open_browser=True,
    )

    def run_process(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[object]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 17)

    exit_code = execute_launch(
        plan,
        open_url=opened.append,
        run_process=run_process,
    )

    assert exit_code == 17
    assert opened == [plan.studio_url]
    command, options = calls[0]
    assert command == list(plan.command)
    assert options["cwd"] == tmp_path
    assert options["check"] is False
    assert options["stdout"] is sys.stderr
    assert options["stderr"] is sys.stderr
