"""Encode bounded runtime-inspection worker requests and responses."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from marimo_studio._notebook.source_generation import NotebookSourceGeneration
from marimo_studio._processes.limits import (
    validate_runtime_timeout,
)
from marimo_studio._projections.runtime_records import (
    MAX_RUNTIME_VALUE_BYTES,
    RuntimeProbe,
    runtime_probe_from_dict,
)
from marimo_studio.errors import ConfigurationError, ProtocolError, RuntimeTimeoutError

RUNTIME_PROTOCOL_SCHEMA = 1
_MAX_REQUEST_BYTES = 256 * 1024
_MAX_JSON_DEPTH = 64
_REQUEST_FIELDS = {
    "schema",
    "notebook",
    "cellIds",
    "variables",
    "outputSelectorGroups",
    "showTracebacks",
    "timeout",
    "valueMaxBytes",
    "sourceGeneration",
}


def encode_runtime_request(
    path: Path,
    *,
    cell_ids: tuple[str, ...],
    variables: tuple[str, ...],
    output_selector_groups: tuple[tuple[str, ...], ...],
    show_tracebacks: bool,
    timeout: float,
    value_max_bytes: int | None,
    source_generation: NotebookSourceGeneration | None,
) -> bytes:
    """Encode one complete worker request after validating its budgets."""
    _validate_timeout(timeout)
    limit = MAX_RUNTIME_VALUE_BYTES if value_max_bytes is None else value_max_bytes
    _validate_value_limit(limit)
    if type(show_tracebacks) is not bool:
        raise ValueError("show_tracebacks must be a boolean")
    payload = {
        "schema": RUNTIME_PROTOCOL_SCHEMA,
        "notebook": str(path),
        "cellIds": list(_strings(cell_ids, "cell_ids")),
        "variables": list(_strings(variables, "variables")),
        "outputSelectorGroups": [
            list(_strings(group, "output_selector_groups"))
            for group in output_selector_groups
        ],
        "showTracebacks": show_tracebacks,
        "timeout": timeout,
        "valueMaxBytes": limit,
        "sourceGeneration": (
            source_generation.to_dict() if source_generation is not None else None
        ),
    }
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("runtime inspection request is not valid JSON") from error
    if len(encoded) > _MAX_REQUEST_BYTES:
        raise ValueError(
            f"runtime inspection request exceeds {_MAX_REQUEST_BYTES} bytes"
        )
    return encoded


def load_runtime_request(path: Path) -> dict[str, Any]:
    """Decode one worker request from its private temporary file."""
    payload = path.read_bytes()
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ProtocolError(
            f"Runtime inspection request exceeds {_MAX_REQUEST_BYTES} bytes"
        )
    try:
        request = _exact_record(_loads_json(payload), _REQUEST_FIELDS)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as error:
        raise ProtocolError("Runtime inspection request is invalid") from error
    if (
        request["schema"] != RUNTIME_PROTOCOL_SCHEMA
        or type(request["schema"]) is not int
    ):
        raise ProtocolError("Runtime inspection request has an invalid schema")
    notebook = request["notebook"]
    show_tracebacks = request["showTracebacks"]
    if not isinstance(notebook, str) or type(show_tracebacks) is not bool:
        raise ProtocolError("Runtime inspection request is invalid")
    try:
        _validate_timeout(request["timeout"])
        _validate_value_limit(request["valueMaxBytes"])
        cell_ids = _strings(request["cellIds"], "cellIds")
        variables = _strings(request["variables"], "variables")
        groups = request["outputSelectorGroups"]
        if not isinstance(groups, list):
            raise ValueError
        output_groups = tuple(
            _strings(group, "outputSelectorGroups") for group in groups
        )
        source_generation = (
            None
            if request["sourceGeneration"] is None
            else NotebookSourceGeneration.from_dict(request["sourceGeneration"])
        )
    except (TypeError, ValueError) as error:
        raise ProtocolError("Runtime inspection request is invalid") from error
    return {
        "notebook": notebook,
        "cell_ids": cell_ids,
        "variables": variables,
        "output_selector_groups": output_groups,
        "show_tracebacks": show_tracebacks,
        "timeout": request["timeout"],
        "value_max_bytes": request["valueMaxBytes"],
        "source_generation": source_generation,
    }


def decode_runtime_response(payload: bytes) -> RuntimeProbe:
    """Decode one successful or expected-error worker response."""
    try:
        response = _record(_loads_json(payload))
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
        RecursionError,
    ) as error:
        raise ProtocolError(
            "Isolated notebook runtime returned invalid JSON"
        ) from error
    if (
        response.get("schema") != RUNTIME_PROTOCOL_SCHEMA
        or type(response.get("schema")) is not int
    ):
        raise ProtocolError("Isolated notebook runtime returned an invalid response")
    if set(response) == {"schema", "error"}:
        try:
            failure = _exact_record(response["error"], {"code", "message"})
        except ValueError as error:
            raise ProtocolError(
                "Isolated notebook runtime returned an invalid error"
            ) from error
        code = failure["code"]
        message = failure["message"]
        if not isinstance(code, str) or not isinstance(message, str):
            raise ProtocolError("Isolated notebook runtime returned an invalid error")
        if code == RuntimeTimeoutError.code:
            raise RuntimeTimeoutError(message)
        if code == ConfigurationError.code:
            raise ConfigurationError(message)
        raise ProtocolError(message)
    if set(response) != {"schema", "runtime"}:
        raise ProtocolError("Isolated notebook runtime returned an invalid response")
    try:
        return runtime_probe_from_dict(response["runtime"])
    except (KeyError, OverflowError, RecursionError, TypeError, ValueError) as error:
        raise ProtocolError(
            "Isolated notebook runtime returned an invalid probe"
        ) from error


def _validate_timeout(value: object) -> None:
    validate_runtime_timeout(value)


def _loads_json(payload: bytes) -> object:
    value = json.loads(
        payload,
        parse_constant=_reject_json_constant,
        parse_float=_parse_json_float,
    )
    _validate_json_depth(value)
    return value


def _validate_json_depth(value: object, depth: int = 0) -> None:
    if not isinstance(value, (dict, list)):
        return
    if depth >= _MAX_JSON_DEPTH:
        raise ValueError(f"JSON exceeds {_MAX_JSON_DEPTH} container levels")
    children = value.values() if isinstance(value, dict) else value
    for child in children:
        _validate_json_depth(child, depth + 1)


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"Invalid JSON constant: {value}")


def _parse_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number is outside the finite range")
    return parsed


def _validate_value_limit(value: object) -> None:
    if type(value) is not int or not 1 <= value <= MAX_RUNTIME_VALUE_BYTES:
        raise ValueError(
            "value_max_bytes must be an integer between 1 and "
            f"{MAX_RUNTIME_VALUE_BYTES}"
        )


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"{field} must contain strings")
    return tuple(value)


def _record(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError
    return value


def _exact_record(value: object, fields: set[str]) -> dict[str, Any]:
    payload = _record(value)
    if set(payload) != fields:
        raise ValueError
    return payload
