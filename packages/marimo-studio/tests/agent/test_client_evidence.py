from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import cast

import pytest

import marimo_studio._browser_client.client as browser_client
import marimo_studio._browser_client.transport as browser_transport
from marimo_studio._validation.analysis import AnalysisRequest
from marimo_studio._validation.evidence import AnalysisReport, BrowserObservation
from marimo_studio.errors import ProtocolError

from ..helpers import ready_runtime_status


def test_http_errors_preserve_structured_details() -> None:
    with pytest.raises(browser_transport.AgentRequestError) as raised:
        browser_transport._raise_response_error(
            404,
            b'{"error":"view-not-found","message":"missing",'
            b'"view":"missing","available_views":["dashboard"]}',
        )

    assert raised.value.diagnostic_details() == {
        "view": "missing",
        "available_views": ["dashboard"],
    }


def test_analysis_transport_budget_covers_runtime_and_browser_deadlines(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("", encoding="utf-8")
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        actions=(),
    )
    captured: dict[str, object] = {}

    async def request(*_args, **kwargs):
        captured.update(kwargs)
        return report.to_dict()

    monkeypatch.setattr(browser_client, "request_json", request)

    asyncio.run(
        browser_client.request_analysis(
            browser_transport.StudioServerConnection(
                "http://localhost:2718",
                server_token="server-token",
            ),
            notebook,
            AnalysisRequest(
                view="dashboard",
                browser_timeout=20,
                runtime_timeout=75,
                require_browser=False,
            ),
        )
    )

    assert captured["timeout"] == 105.0
    body = captured["body"]
    assert isinstance(body, dict)
    assert cast(dict[str, object], body)["schema"] == 1
    assert cast(dict[str, object], body)["runtime_timeout"] == 75


def test_analysis_rejects_a_browser_policy_downgrade(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        actions=(),
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return report.to_dict()

    monkeypatch.setattr(browser_client, "request_json", request)

    with pytest.raises(ProtocolError, match="analysis response"):
        asyncio.run(
            browser_client.request_analysis(
                browser_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                ),
                notebook,
                AnalysisRequest(view="dashboard", require_browser=True),
            )
        )


def test_observation_rejects_evidence_from_another_selected_browser(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    observation = BrowserObservation(
        view="dashboard",
        state="ready",
        runtime="server",
        revision="revision-1",
        client_id="other-browser",
        runtime_instance="runtime-instance",
        session_id="s_123456",
        request_id="request-dashboard",
        sequence=1,
        runtime_status=ready_runtime_status("dashboard", "revision-1"),
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(notebook),
            "observations": [observation.to_dict()],
        }

    monkeypatch.setattr(browser_client, "request_json", request)

    with pytest.raises(ProtocolError, match="another browser"):
        asyncio.run(
            browser_client.observe_browser_views(
                browser_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    browser_client="selected-browser",
                ),
                notebook,
                ("dashboard",),
                revisions={"dashboard": "revision-1"},
            )
        )


@pytest.mark.parametrize(
    ("observed_revision", "observed_runtime"),
    [
        ("wrong-revision", "server"),
        ("revision-1", "wasm"),
    ],
)
def test_observation_rejects_evidence_for_another_revision_or_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    observed_revision: str,
    observed_runtime: str,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    runtime_status = replace(
        ready_runtime_status("dashboard", observed_revision),
        runtime=observed_runtime,
    )
    observation = BrowserObservation(
        view="dashboard",
        state="ready",
        runtime=observed_runtime,
        revision=observed_revision,
        client_id="browser-client-1234",
        runtime_instance="runtime-instance",
        session_id="s_123456",
        request_id="request-dashboard",
        sequence=1,
        runtime_status=runtime_status,
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(notebook),
            "observations": [observation.to_dict()],
        }

    monkeypatch.setattr(browser_client, "request_json", request)

    with pytest.raises(ProtocolError, match=r"another (revision|runtime)"):
        asyncio.run(
            browser_client.observe_browser_views(
                browser_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    browser_client="browser-client-1234",
                ),
                notebook,
                ("dashboard",),
                revisions={"dashboard": "revision-1"},
                runtime="server",
            )
        )


def test_analysis_rejects_evidence_from_another_selected_browser(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view="dashboard",
                state="ready",
                runtime="server",
                revision="revision-1",
                client_id="other-browser",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id="request-dashboard",
                sequence=1,
                runtime_status=ready_runtime_status("dashboard", "revision-1"),
            ),
        ),
        browser_required=True,
        actions=(),
    )

    async def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        return report.to_dict()

    monkeypatch.setattr(browser_client, "request_json", request)

    with pytest.raises(ProtocolError, match="another browser"):
        asyncio.run(
            browser_client.request_analysis(
                browser_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    browser_client="selected-browser",
                ),
                notebook,
                AnalysisRequest(
                    view="dashboard",
                    browser_client="selected-browser",
                ),
            )
        )


def test_code_mode_analysis_rejects_evidence_from_another_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view="dashboard",
                state="ready",
                runtime="server",
                revision="revision-1",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_654321",
                request_id="request-dashboard",
                sequence=1,
            ),
        ),
        browser_required=True,
        actions=(),
    )

    async def request(*_args, **_kwargs):
        return report.to_dict()

    monkeypatch.setattr(browser_client, "request_json", request)

    with pytest.raises(ProtocolError, match="another session"):
        asyncio.run(
            browser_client.request_analysis(
                browser_transport.StudioServerConnection(
                    "http://localhost:2718",
                    server_token="server-token",
                    session_id="s_123456",
                ),
                notebook,
                AnalysisRequest(view="dashboard"),
            )
        )
