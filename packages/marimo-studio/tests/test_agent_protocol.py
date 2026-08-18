from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from marimo_studio._agent_protocol import (
    decode_browser_observation,
    parse_activation_result,
    parse_analysis_report,
    parse_connection_token,
)
from marimo_studio.agent_models import (
    AnalysisReport,
    BrowserDiagnostic,
    BrowserObservation,
    RuntimeStatusReport,
    RuntimeStatusSnapshot,
    RuntimeStatusTransition,
)
from marimo_studio.errors import ProtocolError
from marimo_studio.types import CheckResult

from .helpers import ready_runtime_status


def _runtime_status(
    phase: str,
    diagnostics: list[dict[str, object]],
    revision: str = "revision-1",
) -> dict[str, object]:
    retained = diagnostics[:20]
    return {
        "runtime": "server",
        "view": "dashboard",
        "revision": revision,
        "sessionId": "s_123456",
        "current": {"phase": phase, "diagnostics": diagnostics},
        "transitions": [
            {
                "sequence": 0,
                "observedAt": 1_000,
                "revision": revision,
                "sessionId": "s_123456",
                "phase": phase,
                "diagnostics": retained,
                "diagnosticsTruncated": len(retained) < len(diagnostics),
            }
        ],
    }


def test_connection_protocol_requires_the_target_notebook(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = {
        "schema": 1,
        "notebook": str(notebook),
        "server_token": "server-token",
    }

    assert parse_connection_token(payload, notebook) == "server-token"
    with pytest.raises(ProtocolError, match="connection response"):
        parse_connection_token({**payload, "notebook": "other.py"}, notebook)


def test_analysis_report_round_trips_through_the_agent_protocol(
    tmp_path: Path,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(CheckResult("static", "pass", "Sources are valid"),),
        runtime_checks=(CheckResult("runtime", "pass", "Notebook completed"),),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view="dashboard",
                runtime="server",
                revision="revision-1",
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id="request-dashboard",
                sequence=2,
                query="",
                runtime_status=RuntimeStatusReport(
                    runtime="server",
                    view="dashboard",
                    revision="revision-1",
                    session_id="s_123456",
                    current=RuntimeStatusSnapshot(phase="ready"),
                    transitions=(
                        RuntimeStatusTransition(
                            sequence=0,
                            observed_at=1_000,
                            phase="connecting",
                        ),
                        RuntimeStatusTransition(
                            sequence=1,
                            observed_at=1_100,
                            phase="ready",
                            revision="revision-1",
                            session_id="s_123456",
                        ),
                    ),
                ),
            ),
        ),
        browser_required=True,
        actions=(),
    )

    assert parse_analysis_report(report.to_dict()) == report
    assert report.handoff_ready
    stages = report.to_dict()["stages"]
    assert isinstance(stages, dict)
    browser = stages["browser"]
    assert isinstance(browser, dict)
    observations = browser["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    runtime_status = observation["runtime_status"]
    assert isinstance(runtime_status, dict)
    current = runtime_status["current"]
    assert isinstance(current, dict)
    assert current["phase"] == "ready"


def test_analysis_report_requires_consistent_handoff_evidence(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    report = AnalysisReport(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(CheckResult("static", "pass", "Sources are valid"),),
        runtime_checks=(CheckResult("runtime", "pass", "Notebook completed"),),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view="dashboard",
                runtime="server",
                revision="revision-1",
                state="ready",
                client_id="browser-client-1234",
                runtime_instance="runtime-instance",
                session_id="s_123456",
                request_id="request-dashboard",
                sequence=2,
                runtime_status=ready_runtime_status(
                    "dashboard",
                    "revision-1",
                ),
            ),
        ),
        browser_required=True,
        actions=(),
    )
    failed_static = replace(
        report,
        static_checks=(CheckResult("static", "fail", "Sources are invalid"),),
    )
    missing_runtime = replace(report, runtime_checks=())
    browser_error = replace(
        report,
        browser_observations=(
            replace(
                report.browser_observations[0],
                diagnostics=(
                    BrowserDiagnostic(
                        code="missing-value",
                        severity="error",
                        message="summary is unavailable",
                        hint="Restore summary.",
                        view="dashboard",
                        scope="host",
                    ),
                ),
            ),
        ),
    )
    runtime_status = report.browser_observations[0].runtime_status
    assert runtime_status is not None

    def with_runtime_status(status: RuntimeStatusReport) -> AnalysisReport:
        return replace(
            report,
            browser_observations=(
                replace(report.browser_observations[0], runtime_status=status),
            ),
        )

    mismatched_statuses = (
        replace(runtime_status, runtime="wasm"),
        replace(runtime_status, view="report"),
        replace(runtime_status, revision="revision-2"),
        replace(runtime_status, session_id="s_654321"),
        replace(
            runtime_status,
            transitions=(
                *runtime_status.transitions[:-1],
                replace(runtime_status.transitions[-1], phase="connecting"),
            ),
        ),
    )

    assert failed_static.ok is False
    assert failed_static.handoff_ready is False
    assert failed_static.to_dict()["summary"] == {
        "pass": 2,
        "warn": 0,
        "fail": 1,
    }
    assert missing_runtime.handoff_ready is False
    assert browser_error.ok is False
    assert browser_error.handoff_ready is False
    assert all(
        with_runtime_status(status).handoff_ready is False
        for status in mismatched_statuses
    )
    assert browser_error.to_dict()["summary"] == {
        "pass": 2,
        "warn": 0,
        "fail": 1,
    }

    payload = json.loads(json.dumps(report.to_dict()))
    contradictory = deepcopy(payload)
    contradictory["stages"]["static"]["checks"][0]["status"] = "fail"
    contradictory["stages"]["static"]["status"] = "fail"
    empty_runtime = deepcopy(payload)
    empty_runtime["stages"]["runtime"]["checks"] = []
    ready_with_error = deepcopy(payload)
    ready_with_error["stages"]["browser"]["observations"][0]["diagnostics"] = [
        browser_error.browser_observations[0].diagnostics[0].to_dict()
    ]
    for invalid in (contradictory, empty_runtime, ready_with_error):
        with pytest.raises(
            ProtocolError,
            match=r"analysis response|browser observation",
        ):
            parse_analysis_report(invalid)


def test_analysis_protocol_rejects_unrecognized_fields(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = AnalysisReport(
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
    ).to_dict()
    payload["unexpected"] = True

    with pytest.raises(ProtocolError, match="analysis response"):
        parse_analysis_report(payload)


def test_activation_protocol_rejects_boolean_generations(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = {
        "schema": 1,
        "notebook": str(notebook),
        "view": "dashboard",
        "state": "active",
        "generation": True,
        "transition": "in-place",
        "client_id": "browser-client-1234",
        "session_id": "s_123456",
    }

    with pytest.raises(ProtocolError, match="activation response"):
        parse_activation_result(payload, notebook, "dashboard")


def test_browser_protocol_requires_the_server_observation_challenge() -> None:
    payload = {
        "schema": 1,
        "view": "dashboard",
        "runtime": "server",
        "revision": "revision-1",
        "state": "ready",
        "diagnostics": [],
        "clientId": "browser-client-1234",
        "runtimeInstance": "runtime-instance",
        "sessionId": "s_123456",
        "requestId": "request-dashboard",
        "sequence": 3,
        "query": "",
        "runtimeStatus": _runtime_status("ready", []),
    }

    observation = decode_browser_observation(payload, "dashboard")
    assert observation.request_id == "request-dashboard"
    assert observation.runtime_instance == "runtime-instance"

    with pytest.raises(ProtocolError, match="observation payload"):
        decode_browser_observation({**payload, "unexpected": True}, "dashboard")


@pytest.mark.parametrize(
    ("state", "phase"),
    [
        ("loading", "ready"),
        ("ready", "connecting"),
        ("error", "ready"),
    ],
)
def test_browser_protocol_matches_observation_state_to_runtime_phase(
    state: str,
    phase: str,
) -> None:
    payload = {
        "schema": 1,
        "view": "dashboard",
        "runtime": "server",
        "revision": "revision-1",
        "state": state,
        "diagnostics": [],
        "clientId": "browser-client-1234",
        "runtimeInstance": "runtime-instance",
        "sessionId": "s_123456",
        "requestId": "request-dashboard",
        "sequence": 3,
        "query": "",
        "runtimeStatus": _runtime_status(phase, []),
    }

    with pytest.raises(ProtocolError, match="observation payload"):
        decode_browser_observation(payload, "dashboard")


def test_browser_observation_fixture_matches_the_python_decoder() -> None:
    fixture_root = Path(__file__).parents[2] / "protocol" / "fixtures"
    fixture_path = fixture_root / "browser-observation.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    observation = decode_browser_observation(payload, "dashboard")

    assert observation.client_id == "browser-client-1234"
    assert observation.diagnostics[0].projection == "value"
    assert observation.runtime_status is not None
    assert observation.runtime_status.current.phase == "failed"
    assert [item.phase for item in observation.runtime_status.transitions] == [
        "connecting",
        "failed",
    ]

    invalid_cases = json.loads(
        (fixture_root / "browser-observation-invalid.json").read_text(encoding="utf-8")
    )
    for invalid in invalid_cases:
        with pytest.raises(
            ProtocolError,
            match=r"observation payload|runtime status report",
        ):
            decode_browser_observation(
                {**payload, **invalid["patch"]},
                "dashboard",
            )


def test_loading_browser_evidence_remains_nonterminal_during_error_recovery() -> None:
    payload = {
        "schema": 1,
        "view": "dashboard",
        "runtime": "server",
        "revision": "revision-1",
        "state": "loading",
        "diagnostics": [
            {
                "code": "missing-variable",
                "severity": "error",
                "message": "summary is unavailable.",
                "hint": "Restore summary.",
                "view": "dashboard",
                "scope": "host",
                "target": "summary",
            }
        ],
        "clientId": "browser-client-1234",
        "runtimeInstance": "runtime-instance",
        "sessionId": "s_123456",
        "requestId": "request-dashboard",
        "sequence": 3,
        "query": "",
        "runtimeStatus": _runtime_status(
            "synchronizing",
            [
                {
                    "code": "missing-variable",
                    "severity": "error",
                    "message": "summary is unavailable.",
                    "hint": "Restore summary.",
                    "view": "dashboard",
                    "scope": "host",
                    "target": "summary",
                }
            ],
        ),
    }

    observation = decode_browser_observation(payload, "dashboard")

    assert observation.state == "loading"


def test_truncated_browser_diagnostics_fit_the_server_protocol() -> None:
    diagnostics: list[dict[str, object]] = [
        {
            "code": f"diagnostic-{index}",
            "severity": "error",
            "message": f"Failure {index}",
            "hint": "Fix it.",
            "view": "dashboard",
            "scope": "host",
            "target": f"value-{index}",
        }
        for index in range(199)
    ]
    diagnostics.append(
        {
            "code": "browser-diagnostics-truncated",
            "severity": "error",
            "message": "6 additional browser diagnostics were omitted.",
            "hint": "Fix repeated rendered-view errors, then rerun the analysis.",
            "view": "dashboard",
            "scope": "presentation",
        }
    )
    payload = {
        "schema": 1,
        "view": "dashboard",
        "runtime": "server",
        "revision": "revision-1",
        "state": "error",
        "diagnostics": diagnostics,
        "clientId": "browser-client-1234",
        "runtimeInstance": "runtime-instance",
        "sessionId": "s_123456",
        "requestId": "request-dashboard",
        "sequence": 3,
        "query": "",
        "runtimeStatus": _runtime_status("failed", diagnostics),
    }

    observation = decode_browser_observation(payload, "dashboard")

    assert len(observation.diagnostics) == 200
    assert observation.diagnostics[-1].code == "browser-diagnostics-truncated"
    with pytest.raises(ProtocolError, match="observation payload"):
        decode_browser_observation(
            {**payload, "diagnostics": [*diagnostics, diagnostics[0]]},
            "dashboard",
        )
