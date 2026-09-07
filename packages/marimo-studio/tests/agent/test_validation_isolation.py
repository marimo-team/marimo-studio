from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from click.testing import CliRunner
from starlette.testclient import TestClient

import marimo_studio._authoring.validation as authoring_validation
import marimo_studio._cli.commands.validate as validate_command
import marimo_studio._validation.progressive as analysis_module
import marimo_studio._validation.service as validation_service
import marimo_studio._validation.static as checks_module
import marimo_studio.authoring as studio_authoring
from marimo_studio._cli import cli
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.agent import api as agent_api
from marimo_studio._validation.ports import RuntimeChecker
from marimo_studio._validation.results import CheckResult
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.view_providers import BuildRequest
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import edit_mode, marimo_app, session_manager
from ..async_test_support import wait_for_event


def test_validation_sibling_cleanup_failure_survives_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_started = asyncio.Event()

    async def fail_runtime(*_args: object, **_kwargs: object) -> object:
        await wait_for_event(browser_started)
        raise RuntimeError("runtime validation failed")

    async def observe_browser(*_args: object) -> tuple[()]:
        browser_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError as cancellation:
            raise ProcessCleanupError(
                "browser provider process survived"
            ) from cancellation
        return ()

    monkeypatch.setattr(analysis_module, "run_runtime_validation", fail_runtime)
    preparation: Any = SimpleNamespace(
        views=("dashboard",),
        revisions={"dashboard": "revision"},
    )

    async def exercise() -> None:
        with pytest.raises(
            ProcessCleanupError,
            match="browser provider process survived",
        ) as captured:
            await analysis_module._runtime_and_browser(
                cast(StudioWorkspace, SimpleNamespace()),
                preparation,
                observe_browser=observe_browser,
                runtime_checker=None,
                runtime_timeout=1,
            )
        assert isinstance(captured.value.__cause__, RuntimeError)

    asyncio.run(exercise())


def test_runtime_cleanup_failure_survives_browser_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_started = asyncio.Event()

    async def cleanup_runtime(*_args: object, **_kwargs: object) -> object:
        runtime_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError as cancellation:
            raise ProcessCleanupError(
                "runtime provider process survived"
            ) from cancellation

    async def fail_browser(*_args: object) -> tuple[()]:
        await wait_for_event(runtime_started)
        raise RuntimeError("browser validation failed")

    monkeypatch.setattr(
        analysis_module,
        "run_runtime_validation",
        cleanup_runtime,
    )
    preparation: Any = SimpleNamespace(
        views=("dashboard",),
        revisions={"dashboard": "revision"},
    )

    async def exercise() -> None:
        with pytest.raises(
            ProcessCleanupError,
            match="runtime provider process survived",
        ) as captured:
            await analysis_module._runtime_and_browser(
                cast(StudioWorkspace, SimpleNamespace()),
                preparation,
                observe_browser=fail_browser,
                runtime_checker=None,
                runtime_timeout=1,
            )
        assert isinstance(captured.value.__cause__, RuntimeError)

    asyncio.run(exercise())


def test_python_runtime_validation_uses_the_supervised_process_boundary(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = studio_authoring.open_workspace(notebook_path)
    calls: list[tuple[str | None, dict[str, str] | None, float]] = []

    async def isolated(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = 60,
    ) -> tuple[CheckResult, ...]:
        calls.append((view_name, expected_revisions, timeout))
        return (CheckResult("runtime", "pass", "isolated runtime"),)

    async def in_process(*_args: object, **_kwargs: object) -> tuple[CheckResult, ...]:
        raise AssertionError("Agent validation bypassed process supervision")

    monkeypatch.setattr(
        authoring_validation,
        "check_runtime_studio_isolated",
        isolated,
    )
    monkeypatch.setattr(checks_module, "check_runtime_studio", in_process)

    async def exercise():
        await workspace.create_view("dashboard")
        return await workspace.validate(
            level="runtime",
            view="dashboard",
            runtime_timeout=7,
        )

    report = asyncio.run(exercise())

    assert report.ok
    assert len(calls) == 1
    assert calls[0][0] == "dashboard"
    assert calls[0][1] is not None and set(calls[0][1]) == {"dashboard"}
    assert calls[0][2] == 7
    assert report.evidence["runtime"] == {
        "checks": [CheckResult("runtime", "pass", "isolated runtime").to_dict()]
    }


def test_validation_rejects_source_mutation_between_static_and_runtime_stages(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(studio_authoring.open_workspace(notebook_path).create_view("dashboard"))
    selected = load_studio(notebook_path)
    document = selected.view("dashboard").root / "index.html"
    native_check = validation_service.check_studio
    runtime_called = False

    def mutate_after_static(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        _published_mounts: Any = None,
    ):
        report = native_check(
            studio,
            view_name=view_name,
            _published_mounts=_published_mounts,
        )
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "</body>", "<p>changed</p></body>"
            ),
            encoding="utf-8",
        )
        return report

    async def runtime(*_args: object, **_kwargs: object) -> tuple[CheckResult, ...]:
        nonlocal runtime_called
        runtime_called = True
        return ()

    monkeypatch.setattr(validation_service, "check_studio", mutate_after_static)

    run = asyncio.run(
        validation_service.validate_studio(
            selected,
            level="runtime",
            view_name="dashboard",
            runtime_checker=runtime,
        )
    )

    assert not runtime_called
    assert run.report.ok is False
    assert run.static.checks[-1].code == "validation-source-changed"


def test_static_validation_rejects_notebook_changes_during_build(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = studio_authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    provider = provider_registry().get(
        load_studio(notebook_path).view("dashboard").provider
    )
    build = provider.build

    def change_notebook(request: BuildRequest):
        result = build(request)
        notebook_path.write_text(
            notebook_path.read_text(encoding="utf-8") + "\n# Updated analysis\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(provider, "build", change_notebook)

    report = asyncio.run(workspace.validate(level="static", view="dashboard"))

    assert not report.ok
    assert any(issue.code == "validation-source-changed" for issue in report.issues)


def test_static_validation_rejects_changed_provider_mounts(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = studio_authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    project = load_studio(notebook_path).view("dashboard")
    provider = provider_registry().get(project.provider)
    build = provider.build
    inspect = provider.inspect
    changed = False

    def inspect_mounts(request: Any):
        inspection = inspect(request)
        return (
            replace(
                inspection,
                mounts=tuple(
                    replace(mount, allowed_targets=None) for mount in inspection.mounts
                ),
            )
            if changed
            else inspection
        )

    def change_mounts(request: BuildRequest):
        nonlocal changed
        result = build(request)
        changed = True
        return result

    monkeypatch.setattr(provider, "inspect", inspect_mounts)
    monkeypatch.setattr(provider, "build", change_mounts)

    report = asyncio.run(workspace.validate(level="static", view="dashboard"))

    assert not report.ok
    assert any(issue.code == "validation-source-changed" for issue in report.issues)


def _validation_entry_reports(
    workspace: studio_authoring.Workspace,
    monkeypatch: pytest.MonkeyPatch,
    checker: RuntimeChecker,
    *,
    restore: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    notebook = workspace.notebook
    monkeypatch.setattr(
        authoring_validation,
        "check_runtime_studio_isolated",
        checker,
    )
    monkeypatch.setattr(validate_command, "should_reenter", lambda *_args: False)
    monkeypatch.setattr(agent_api, "check_runtime_studio_isolated", checker)

    python_report = asyncio.run(
        workspace.validate(
            level="runtime",
            view="dashboard",
            runtime_timeout=7,
        )
    ).to_dict()
    if restore is not None:
        restore()
    cli_result = CliRunner().invoke(
        cli,
        [
            "validate",
            "dashboard",
            "--target",
            str(notebook),
            "--level",
            "runtime",
            "--runtime-timeout",
            "7",
            "--json",
        ],
    )
    assert cli_result.exit_code == 1, cli_result.output
    cli_report = json.loads(cli_result.stdout)
    if restore is not None:
        restore()

    app = marimo_app(notebook)
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}
    with TestClient(app) as client:
        response = client.post(
            "/_marimo-studio/validate",
            headers=headers,
            json={
                "schema": 1,
                "view": "dashboard",
                "runtime_timeout": 7,
                "require_browser": False,
            },
        )
    if restore is not None:
        restore()
    assert response.status_code == 200
    return python_report, cli_report, response.json()


def test_runtime_failure_is_identical_through_python_cli_and_server_validation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = studio_authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    failure = CheckResult(
        "runtime",
        "fail",
        "The isolated worker crashed.",
        code="runtime-check-failed",
        details={
            "source": {"path": str(notebook_path)},
            "hint": "Repair the notebook runtime and rerun validation.",
        },
    )
    calls: list[dict[str, str] | None] = []

    async def isolated(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = 60,
    ) -> tuple[CheckResult, ...]:
        del studio
        assert view_name == "dashboard"
        assert timeout == 7
        calls.append(expected_revisions)
        return (failure,)

    python_report, cli_report, server_report = _validation_entry_reports(
        workspace,
        monkeypatch,
        isolated,
    )

    assert cli_report == python_report
    assert server_report["stages"]["runtime"]["checks"] == [failure.to_dict()]
    assert server_report["issues"] == python_report["issues"]
    assert len(calls) == 3
    assert all(
        revisions is not None and set(revisions) == {"dashboard"} for revisions in calls
    )


@pytest.mark.parametrize(
    ("outcome", "code", "advice"),
    (
        (
            "changed",
            "validation-source-changed",
            "Wait for the current edits to save, then rerun validation.",
        ),
        (
            "unavailable",
            "validation-source-unavailable",
            "Restore the missing source, save it, then rerun validation.",
        ),
    ),
)
def test_source_revision_failures_match_python_cli_and_server_validation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    code: str,
    advice: str,
) -> None:
    workspace = studio_authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    source = load_studio(notebook_path).view("dashboard").root / "index.html"
    original = source.read_text(encoding="utf-8")
    notebook_source = notebook_path.read_text(encoding="utf-8")

    async def isolated(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = 60,
    ) -> tuple[CheckResult, ...]:
        del studio
        assert view_name == "dashboard"
        assert expected_revisions is not None
        assert timeout == 7
        if outcome == "changed":
            source.write_text(f"{original}\n<!-- changed -->\n", encoding="utf-8")
        else:
            notebook_path.unlink()
        return (CheckResult("runtime", "pass", "isolated runtime"),)

    def restore() -> None:
        source.write_text(original, encoding="utf-8")
        notebook_path.write_text(notebook_source, encoding="utf-8")

    python_report, cli_report, server_report = _validation_entry_reports(
        workspace,
        monkeypatch,
        isolated,
        restore=restore,
    )

    assert python_report == cli_report
    checks = (
        python_report["evidence"]["runtime"]["checks"],
        cli_report["evidence"]["runtime"]["checks"],
        server_report["stages"]["runtime"]["checks"],
    )
    source_checks = [
        next(check for check in stage if check.get("code") == code) for stage in checks
    ]
    assert source_checks[0] == source_checks[1] == source_checks[2]
    assert source_checks[0]["name"] == "validation-source-revision"
    source_issues = [
        next(issue for issue in report["issues"] if issue["code"] == code)
        for report in (python_report, cli_report, server_report)
    ]
    assert source_issues[0] == source_issues[1] == source_issues[2]
    assert source_issues[0]["advice"] == advice


def test_invalid_static_source_matches_python_cli_and_server_validation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = studio_authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    source = load_studio(notebook_path).view("dashboard").root / "index.html"
    original = source.read_text(encoding="utf-8")
    native_check = validation_service.check_studio
    runtime_calls = 0

    def invalidate_after_static(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        _published_mounts: Any = None,
    ):
        report = native_check(
            studio,
            view_name=view_name,
            _published_mounts=_published_mounts,
        )
        source.write_text(
            original.replace('id="app-shell"', 'id="broken-shell"'),
            encoding="utf-8",
        )
        return report

    async def runtime(
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = 60,
    ) -> tuple[CheckResult, ...]:
        nonlocal runtime_calls
        del studio, view_name, expected_revisions, timeout
        runtime_calls += 1
        return ()

    def restore() -> None:
        source.write_text(original, encoding="utf-8")

    monkeypatch.setattr(validation_service, "check_studio", invalidate_after_static)
    python_report, cli_report, server_report = _validation_entry_reports(
        workspace,
        monkeypatch,
        runtime,
        restore=restore,
    )

    assert runtime_calls == 0
    assert python_report == cli_report
    checks = (
        python_report["evidence"]["static"]["checks"],
        cli_report["evidence"]["static"]["checks"],
        server_report["stages"]["static"]["checks"],
    )
    source_checks = [
        next(
            check for check in stage if check.get("code") == "validation-source-changed"
        )
        for stage in checks
    ]
    assert source_checks[0] == source_checks[1] == source_checks[2]
    source_issues = [
        next(
            issue
            for issue in report["issues"]
            if issue["code"] == "validation-source-changed"
        )
        for report in (python_report, cli_report, server_report)
    ]
    assert source_issues[0] == source_issues[1] == source_issues[2]
