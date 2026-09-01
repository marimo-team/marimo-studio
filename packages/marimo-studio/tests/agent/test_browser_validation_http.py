from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from marimo_studio._compat.server.session_state import PrivateSessionState
from marimo_studio._server.agent import api as agent_api
from marimo_studio._validation import service as validation_service
from marimo_studio._validation.evidence import BrowserObservation
from marimo_studio._validation.results import CheckResult
from marimo_studio._views.presentation_publication import PresentationPublication
from marimo_studio._views.revisions import PreparedViewProject
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.view_providers import BuildProfile

from ..agent_support import agent_edit_server
from ..helpers import ready_runtime_status


def test_edit_server_runs_the_agent_handoff_analysis(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = agent_edit_server(notebook_path)
    runtime_calls: list[dict[str, object]] = []

    async def runtime(
        *_args: object,
        **kwargs: object,
    ) -> tuple[CheckResult, ...]:
        runtime_calls.append(kwargs)
        return (CheckResult("runtime", "pass", "Notebook run completed"),)

    async def observe(
        _context: object,
        _presentation: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
        **_kwargs: object,
    ) -> tuple[BrowserObservation, ...]:
        return tuple(
            BrowserObservation(
                view=view,
                runtime="server",
                revision=revisions[view],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id=f"request-{view}",
                sequence=index,
                query="",
                runtime_status=ready_runtime_status(view, revisions[view]),
            )
            for index, view in enumerate(views)
        )

    monkeypatch.setattr(agent_api, "check_runtime_studio_isolated", runtime)
    monkeypatch.setattr(agent_api, "observe_views", observe)

    with TestClient(server.app) as client:
        analyzed = client.post(
            "/_marimo-studio/validate",
            headers=server.headers,
            json={
                "schema": 1,
                "view": "dashboard",
                "browser_timeout": 0,
                "runtime_timeout": 75,
                "require_browser": True,
            },
        )

    assert analyzed.status_code == 200
    assert analyzed.json()["ok"] is True
    assert analyzed.json()["stages"]["browser"]["status"] == "ready"
    assert analyzed.json()["issues"] == []
    assert runtime_calls[0]["timeout"] == 75


def test_code_mode_analysis_requires_one_named_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = agent_edit_server(notebook_path, session_id="s_123456")
    observed: list[dict[str, object]] = []

    async def runtime(*_args: object, **_kwargs: object) -> tuple[CheckResult, ...]:
        return (CheckResult("runtime", "pass", "Notebook run completed"),)

    async def observe(
        _context: object,
        _presentation: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
        **kwargs: object,
    ) -> tuple[BrowserObservation, ...]:
        observed.append(
            {
                key: value
                for key, value in kwargs.items()
                if key not in {"sessions", "runtimes"}
            }
        )
        return (
            BrowserObservation(
                view=views[0],
                runtime="server",
                revision=revisions[views[0]],
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                request_id="request-dashboard",
                sequence=1,
                session_id="s_123456",
                query="",
                runtime_status=ready_runtime_status(
                    views[0],
                    revisions[views[0]],
                ),
            ),
        )

    monkeypatch.setattr(PrivateSessionState, "exists", lambda *_args: True)
    monkeypatch.setattr(agent_api, "check_runtime_studio_isolated", runtime)
    monkeypatch.setattr(agent_api, "observe_views", observe)

    with TestClient(server.app) as client:
        unfocused = client.post(
            "/_marimo-studio/validate",
            headers=server.headers,
            json={"schema": 1, "browser_timeout": 0, "require_browser": True},
        )
        focused = client.post(
            "/_marimo-studio/validate",
            headers=server.headers,
            json={
                "schema": 1,
                "view": "dashboard",
                "browser_timeout": 0,
                "require_browser": True,
            },
        )

    assert unfocused.status_code == 400
    assert unfocused.json()["error"] == "focused-view-required"
    assert focused.status_code == 200
    assert focused.json()["ok"] is True
    assert observed == [
        {
            "runtime": "server",
            "timeout": 0.0,
            "session_id": "s_123456",
            "client_id": None,
            "allow_view_activation": False,
        }
    ]


def test_code_mode_validation_rejects_a_replacement_before_publication(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = agent_edit_server(notebook_path, session_id="s_123456")
    root = server.studio.views["dashboard"].root
    retired = root.with_name("retired-dashboard")
    publish_presentation = validation_service.publish_presentation
    replaced = False

    def replace_then_publish(
        studio: StudioWorkspace,
        view_name: str,
        prepared: PreparedViewProject | None = None,
        *,
        profile: BuildProfile = "development",
        expected_catalog_generation: str | None = None,
        expected_generation: str | None = None,
    ) -> PresentationPublication:
        nonlocal replaced
        if not replaced:
            root.rename(retired)
            shutil.copytree(retired, root)
            shutil.rmtree(root / ".artifacts")
            replaced = True
        return publish_presentation(
            studio,
            view_name,
            prepared,
            profile=profile,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
        )

    monkeypatch.setattr(PrivateSessionState, "exists", lambda *_args: True)
    monkeypatch.setattr(
        validation_service,
        "publish_presentation",
        replace_then_publish,
    )

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/validate",
            headers=server.headers,
            json={
                "schema": 1,
                "view": "dashboard",
                "browser_timeout": 0,
                "require_browser": True,
                "catalog_generation": server.studio.catalog_generation,
                "view_generation": server.studio.view_generations["dashboard"],
            },
        )

    assert replaced
    assert response.status_code == 409
    assert response.json()["error"] == "view-generation-conflict"
    assert not root.joinpath(".artifacts").exists()


def test_agent_analysis_rejects_noncanonical_request_records(
    notebook_path: Path,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/validate",
            headers=server.headers,
            json={"schema": 1, "view": "dashboard", "unexpected": True},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-validation-request"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_timeout", 301),
        ("browser_timeout", 10**1000),
    ],
)
def test_agent_analysis_rejects_an_out_of_range_timeout(
    notebook_path: Path,
    field: str,
    value: int,
) -> None:
    server = agent_edit_server(notebook_path)

    with TestClient(server.app) as client:
        response = client.post(
            "/_marimo-studio/validate",
            headers=server.headers,
            json={"schema": 1, "view": "dashboard", field: value},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-validation-request"
    assert response.json()["field"] == field
