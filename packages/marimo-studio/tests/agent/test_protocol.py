from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from marimo_studio._browser_client.protocol import (
    decode_browser_observation,
    parse_connection_token,
    parse_observation_response,
    parse_show_result,
    parse_validation_evidence,
)
from marimo_studio._browser_client.records import ShowResult
from marimo_studio._validation.evidence import (
    BrowserDiagnostic,
    BrowserObservation,
    RuntimeStatusReport,
    ValidationEvidence,
)
from marimo_studio._validation.results import CheckResult
from marimo_studio.errors import ProtocolError

from ..helpers import ready_runtime_status

pytestmark = pytest.mark.supported_python


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


def _empty_projection_evidence() -> dict[str, object]:
    return {"projectionInstances": []}


def _ready_validation_evidence(
    tmp_path: Path,
    *,
    runtime: str,
    session_id: str | None,
) -> ValidationEvidence:
    revision = "revision-1"
    view = "dashboard"
    return ValidationEvidence(
        notebook=(tmp_path / "analysis.py").resolve(),
        views=(view,),
        runtime=runtime,
        revisions={view: revision},
        static_checks=(CheckResult("static", "pass", "Sources are valid"),),
        runtime_checks=(CheckResult("runtime", "pass", "Notebook completed"),),
        runtime_skipped=None,
        browser_observations=(
            BrowserObservation(
                view=view,
                runtime=runtime,
                revision=revision,
                state="ready",
                client_id="browser-client-1234",
                runtime_instance=f"{runtime}-instance",
                session_id=session_id,
                request_id="request-dashboard",
                sequence=2,
                query="",
                runtime_status=ready_runtime_status(
                    view,
                    revision,
                    session_id,
                    runtime=runtime,
                ),
            ),
        ),
        browser_required=True,
        issues=(),
        dynamic_browser_required=True,
    )


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
    with pytest.raises(ProtocolError, match="connection response"):
        parse_connection_token({**payload, "schema": True}, notebook)


def test_validation_report_round_trips_through_the_agent_protocol(
    tmp_path: Path,
) -> None:
    report = _ready_validation_evidence(
        tmp_path,
        runtime="server",
        session_id="s_123456",
    )

    parsed = parse_validation_evidence(report.to_dict())
    assert parsed == report
    assert parsed.dynamic_browser_required is True
    assert report.ok


def test_wasm_analysis_round_trip_accepts_coherent_null_runtime_session(
    tmp_path: Path,
) -> None:
    report = _ready_validation_evidence(
        tmp_path,
        runtime="wasm",
        session_id=None,
    )
    parsed = parse_validation_evidence(report.to_dict())
    observation = report.browser_observations[0]
    runtime_status = observation.runtime_status
    assert runtime_status is not None

    assert parsed == report
    assert parsed.ok
    assert not replace(
        report,
        browser_observations=(
            replace(
                observation,
                session_id="s_123456",
                runtime_status=replace(
                    runtime_status,
                    session_id="s_123456",
                    transitions=(
                        *runtime_status.transitions[:-1],
                        replace(
                            runtime_status.transitions[-1],
                            session_id="s_123456",
                        ),
                    ),
                ),
            ),
        ),
    ).ok


def test_validation_report_requires_coherent_browser_evidence(tmp_path: Path) -> None:
    report = _ready_validation_evidence(
        tmp_path,
        runtime="server",
        session_id="s_123456",
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

    def with_runtime_status(status: RuntimeStatusReport) -> ValidationEvidence:
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
    assert failed_static.to_dict()["summary"] == {
        "pass": 2,
        "warn": 0,
        "fail": 1,
    }
    assert missing_runtime.ok is False
    assert browser_error.ok is False
    assert all(
        with_runtime_status(status).ok is False for status in mismatched_statuses
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
            match=r"validation response|browser observation",
        ):
            parse_validation_evidence(invalid)


def test_validation_protocol_rejects_unrecognized_fields(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = ValidationEvidence(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        issues=(),
    ).to_dict()
    payload["unexpected"] = True

    with pytest.raises(ProtocolError, match="validation response"):
        parse_validation_evidence(payload)

    payload.pop("unexpected")
    payload["schema"] = True
    with pytest.raises(ProtocolError, match="validation response"):
        parse_validation_evidence(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ok", 1),
        ("summary", {"pass": True, "warn": 0, "fail": 0}),
        ("summary", {"pass": -1, "warn": 0, "fail": 0}),
        ("summary", {"pass": 1, "warn": 0}),
    ],
)
def test_validation_protocol_rejects_noncanonical_summary_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = ValidationEvidence(
        notebook=notebook,
        views=("dashboard",),
        runtime="server",
        revisions={"dashboard": "revision-1"},
        static_checks=(),
        runtime_checks=(),
        runtime_skipped=None,
        browser_observations=(),
        browser_required=False,
        issues=(),
    ).to_dict()
    payload[field] = value

    with pytest.raises(ProtocolError, match="validation response"):
        parse_validation_evidence(payload)


def _show_payload(notebook: Path) -> dict[str, object]:
    return {
        "schema": 1,
        "notebook": str(notebook),
        "view": "dashboard",
        "generation": 1,
        "client_id": "browser-client-1234",
        "session_id": "s_123456",
        "preview_url": "http://localhost/preview/",
        "frame_selector": "iframe[data-browser-owned-selector]",
    }


def test_show_protocol_accepts_identity_results(tmp_path: Path) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    active = parse_show_result(
        _show_payload(notebook),
        notebook,
        "dashboard",
    )
    assert active.client_id == "browser-client-1234"
    assert active.frame_selector == "iframe[data-browser-owned-selector]"
    assert active.preview_url == "http://localhost/preview/"


@pytest.mark.parametrize(
    "patch",
    [
        {"schema": True},
        {"generation": True},
        {"unexpected": True},
    ],
)
def test_show_protocol_rejects_invalid_results(
    tmp_path: Path,
    patch: dict[str, object],
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = {**_show_payload(notebook), **patch}

    with pytest.raises(ProtocolError, match="show response"):
        parse_show_result(payload, notebook, "dashboard")


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
        **_empty_projection_evidence(),
        "runtimeStatus": _runtime_status("ready", []),
    }

    observation = decode_browser_observation(payload, "dashboard")
    assert observation.request_id == "request-dashboard"
    assert observation.runtime_instance == "runtime-instance"

    with pytest.raises(ProtocolError, match="observation payload"):
        decode_browser_observation({**payload, "unexpected": True}, "dashboard")
    with pytest.raises(ProtocolError, match="observation payload"):
        decode_browser_observation({**payload, "schema": True}, "dashboard")
    with pytest.raises(ProtocolError, match="observation response"):
        parse_observation_response(
            {
                "schema": True,
                "notebook": "/tmp/analysis.py",
                "observations": [observation.to_dict()],
            },
            ("dashboard",),
        )


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
        **_empty_projection_evidence(),
        "runtimeStatus": _runtime_status(phase, []),
    }

    with pytest.raises(ProtocolError, match="observation payload"):
        decode_browser_observation(payload, "dashboard")


def test_browser_observation_fixture_matches_the_python_decoder() -> None:
    fixture_root = Path(__file__).parents[3] / "protocol" / "fixtures"
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
            match=(
                r"observation payload|runtime status report|runtime status transition"
            ),
        ):
            decode_browser_observation(
                {**payload, **invalid["patch"]},
                "dashboard",
            )


def test_browser_diagnostic_details_survive_agent_observation_serialization() -> None:
    fixture_path = (
        Path(__file__).parents[3] / "protocol" / "fixtures" / "browser-observation.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    details = {
        "state": {"name": "baseline", "inputs": {"scale": 2}},
        "attempts": [{"retryable": True, "elapsed": 0.5, "result": None}],
    }
    for diagnostics in (
        payload["diagnostics"],
        payload["runtimeStatus"]["current"]["diagnostics"],
        payload["runtimeStatus"]["transitions"][-1]["diagnostics"],
    ):
        diagnostics[0]["details"] = deepcopy(details)

    observation = decode_browser_observation(payload, "dashboard")
    for diagnostics in (
        payload["diagnostics"],
        payload["runtimeStatus"]["current"]["diagnostics"],
        payload["runtimeStatus"]["transitions"][-1]["diagnostics"],
    ):
        diagnostics[0]["details"]["state"]["inputs"]["scale"] = 99
    serialized = cast(dict[str, Any], observation.to_dict())
    for diagnostic in (
        serialized["diagnostics"][0],
        serialized["runtime_status"]["current"]["diagnostics"][0],
        serialized["runtime_status"]["transitions"][-1]["diagnostics"][0],
    ):
        assert diagnostic["details"] == details
        diagnostic["details"]["state"]["inputs"]["scale"] = 99

    copied = cast(dict[str, Any], observation.to_dict())
    assert copied["diagnostics"][0]["details"] == details
    assert copied["runtime_status"]["current"]["diagnostics"][0]["details"] == details
    assert (
        copied["runtime_status"]["transitions"][-1]["diagnostics"][0]["details"]
        == details
    )


@pytest.mark.parametrize(
    "details",
    [
        None,
        [],
        "invalid",
        {"value": object()},
        {"value": float("nan")},
        {"value": {1}},
        {"value": (1, 2)},
        {"value": {1: "label"}},
    ],
)
def test_browser_decoder_rejects_malformed_diagnostic_details(details: object) -> None:
    fixture_path = (
        Path(__file__).parents[3] / "protocol" / "fixtures" / "browser-observation.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    payload["diagnostics"][0]["details"] = details

    with pytest.raises(ProtocolError, match="diagnostic"):
        decode_browser_observation(payload, "dashboard")


def test_browser_decoder_rejects_ready_state_with_failed_mounts() -> None:
    fixture_root = Path(__file__).parents[3] / "protocol" / "fixtures"
    payload = json.loads(
        fixture_root.joinpath("browser-observation.json").read_text(encoding="utf-8")
    )

    ready = deepcopy(payload)
    ready["state"] = "ready"
    ready["diagnostics"] = []
    ready["runtimeStatus"]["current"] = {"phase": "ready", "diagnostics": []}
    ready["runtimeStatus"]["transitions"] = [
        {
            "sequence": 1,
            "observedAt": 1_100,
            "revision": "revision-1",
            "sessionId": "s_123456",
            "phase": "ready",
            "diagnostics": [],
            "diagnosticsTruncated": False,
        }
    ]
    with pytest.raises(ProtocolError, match=r"projection|observation payload"):
        decode_browser_observation(ready, "dashboard")


def test_browser_decoder_retains_bounded_projection_failure_evidence() -> None:
    fixture_root = Path(__file__).parents[3] / "protocol" / "fixtures"
    payload = json.loads(
        fixture_root.joinpath("browser-observation.json").read_text(encoding="utf-8")
    )

    empty = deepcopy(payload)
    empty["projectionInstances"][0]["target"] = ""
    empty["projectionInstances"][0]["error"]["code"] = "projection-target-empty"
    assert (
        decode_browser_observation(empty, "dashboard").projection_instances[0].target
        == ""
    )

    overflow = cast(dict[str, Any], deepcopy(payload))
    overflow["projectionInstances"] = [
        {
            **deepcopy(payload["projectionInstances"][0]),
            "instanceId": f"projection-{index}",
        }
        for index in range(513)
    ]
    instances = cast(list[dict[str, Any]], overflow["projectionInstances"])
    error = cast(dict[str, object], instances[-1]["error"])
    error["code"] = "projection-instance-limit"
    assert (
        len(decode_browser_observation(overflow, "dashboard").projection_instances)
        == 513
    )

    instances.append(
        {
            **deepcopy(payload["projectionInstances"][0]),
            "instanceId": "projection-513",
        }
    )
    with pytest.raises(ProtocolError, match="projection instances"):
        decode_browser_observation(overflow, "dashboard")


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
        **_empty_projection_evidence(),
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
            "hint": "Fix repeated rendered-view errors, then rerun validation.",
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
        **_empty_projection_evidence(),
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("preview_url", None),
        ("preview_url", "https://"),
        ("preview_url", "http://localhost:invalid/"),
        ("preview_url", "http://localhost:65536/"),
        ("frame_selector", None),
        ("frame_selector", 7),
    ],
)
def test_show_protocol_requires_browser_automation_target(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    notebook = (tmp_path / "analysis.py").resolve()
    payload = _show_payload(notebook)
    with pytest.raises(ProtocolError):
        parse_show_result({**payload, field: value}, notebook, "dashboard")
    del payload[field]
    with pytest.raises(ProtocolError):
        parse_show_result(payload, notebook, "dashboard")


def test_show_result_preserves_positional_identity_fields(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    result = ShowResult(
        notebook,
        "dashboard",
        2,
        "s_123456",
        "browser-client-1234",
        preview_url="http://localhost/preview/",
        frame_selector="iframe[data-test-preview]",
    )
    assert result.to_dict() == {
        **_show_payload(notebook),
        "generation": 2,
        "frame_selector": "iframe[data-test-preview]",
    }
