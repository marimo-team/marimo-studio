"""Decode progressive validation evidence from Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from marimo_studio._browser_client.browser_protocol import parse_browser_observation
from marimo_studio._validation.evidence import ValidationEvidence, ValidationIssue
from marimo_studio._validation.results import CheckResult
from marimo_studio.errors import ProtocolError


def parse_validation_evidence(payload: dict[str, Any]) -> ValidationEvidence:
    notebook = payload.get("notebook")
    views = payload.get("views")
    runtime_id = payload.get("runtime")
    revisions = payload.get("revisions")
    ok = payload.get("ok")
    summary = payload.get("summary")
    stages = payload.get("stages")
    issues = payload.get("issues")
    if (
        set(payload)
        != {
            "schema",
            "notebook",
            "views",
            "runtime",
            "revisions",
            "ok",
            "summary",
            "stages",
            "issues",
        }
        or type(payload.get("schema")) is not int
        or payload.get("schema") != 1
        or not _nonempty(notebook)
        or not isinstance(views, list)
        or not all(_nonempty(view) for view in views)
        or not _nonempty(runtime_id)
        or not _string_mapping(revisions)
        or type(ok) is not bool
        or not _summary_counts(summary)
        or not isinstance(stages, dict)
        or not isinstance(issues, list)
    ):
        raise ProtocolError("The Studio validation response is invalid.")
    revision_map = cast(dict[str, str], revisions)
    if set(revision_map) != set(views):
        raise ProtocolError("The Studio validation response is invalid.")
    static = stages.get("static")
    runtime = stages.get("runtime")
    browser = stages.get("browser")
    if (
        not isinstance(static, dict)
        or not isinstance(runtime, dict)
        or not isinstance(browser, dict)
        or not isinstance(static.get("checks"), list)
        or not isinstance(runtime.get("checks"), list)
        or not isinstance(browser.get("observations"), list)
        or not isinstance(browser.get("required"), bool)
        or not isinstance(browser.get("required_for_dynamic_sites"), bool)
        or (
            runtime.get("reason") is not None
            and not isinstance(runtime.get("reason"), str)
        )
    ):
        raise ProtocolError("The Studio validation response is invalid.")
    report = ValidationEvidence(
        notebook=Path(cast(str, notebook)).resolve(),
        views=tuple(cast(list[str], views)),
        runtime=cast(str, runtime_id),
        revisions=revision_map,
        static_checks=tuple(_parse_check(item) for item in static["checks"]),
        runtime_checks=tuple(_parse_check(item) for item in runtime["checks"]),
        runtime_skipped=cast(str | None, runtime.get("reason")),
        browser_observations=tuple(
            parse_browser_observation(item) for item in browser["observations"]
        ),
        browser_required=browser["required"],
        issues=tuple(_parse_issue(item) for item in issues),
        dynamic_browser_required=browser["required_for_dynamic_sites"],
    )
    if payload != report.to_dict():
        raise ProtocolError("The Studio validation response is invalid.")
    return report


def _parse_check(value: object) -> CheckResult:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio validation check is invalid.")
    name = value.get("name")
    status = value.get("status")
    message = value.get("message")
    code = value.get("code")
    details = value.get("details")
    if (
        not isinstance(name, str)
        or status not in {"pass", "warn", "fail"}
        or not isinstance(message, str)
        or (code is not None and not isinstance(code, str))
        or (details is not None and not _string_keyed_mapping(details))
    ):
        raise ProtocolError("A Studio validation check is invalid.")
    return CheckResult(
        name=name,
        status=cast(Literal["pass", "warn", "fail"], status),
        message=message,
        code=code,
        details=cast(dict[str, Any] | None, details),
    )


def _parse_issue(value: object) -> ValidationIssue:
    if not isinstance(value, dict):
        raise ProtocolError("A Studio validation issue is invalid.")
    stage = value.get("stage")
    severity = value.get("severity")
    code = value.get("code")
    message = value.get("message")
    advice = value.get("advice")
    view = value.get("view")
    target = value.get("target")
    source = value.get("source")
    if (
        stage not in {"validation", "static", "runtime", "browser"}
        or severity not in {"warning", "error"}
        or not isinstance(code, str)
        or not isinstance(message, str)
        or not isinstance(advice, str)
        or (view is not None and not isinstance(view, str))
        or (target is not None and not isinstance(target, str))
        or (source is not None and not _string_keyed_mapping(source))
    ):
        raise ProtocolError("A Studio validation issue is invalid.")
    return ValidationIssue(
        stage=cast(Literal["validation", "static", "runtime", "browser"], stage),
        severity=cast(Literal["warning", "error"], severity),
        code=code,
        message=message,
        advice=advice,
        view=view,
        target=target,
        source=cast(dict[str, object] | None, source),
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _string_mapping(value: object) -> bool:
    return isinstance(value, dict) and all(
        _nonempty(key) and _nonempty(item) for key, item in value.items()
    )


def _string_keyed_mapping(value: object) -> bool:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _summary_counts(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"pass", "warn", "fail"}
        and all(type(count) is int and count >= 0 for count in value.values())
    )
