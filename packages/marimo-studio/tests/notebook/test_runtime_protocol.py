"""Protect the runtime-inspection worker record protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marimo_studio._notebook.runtime_protocol import (
    _validate_json_depth,
    decode_runtime_response,
    load_runtime_request,
)
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    RenderedOutput,
    RuntimeCell,
    RuntimeOutput,
    RuntimeProbe,
    ValueReadError,
    ValueReadResult,
)
from marimo_studio.errors import ProtocolError


def _nested_value(depth: int) -> object:
    value: object = 0
    for _index in range(depth):
        value = [value]
    return value


def test_runtime_protocol_round_trips_complete_probe() -> None:
    runtime = RuntimeProbe(
        cells={
            "cell": RuntimeCell(
                status="idle",
                outputs=(RuntimeOutput("output", "text/html", False),),
                errors=(),
            )
        },
        values=ValueReadResult(
            values={"count": {"current": 3}},
            errors={"missing": ValueReadError("missing", "No value")},
        ),
        outputs=OutputRenderResult(
            outputs={
                "chart": RenderedOutput(
                    owner_cell_id="cell",
                    mimetype="text/html",
                    data="<div>chart</div>",
                    timestamp=10.5,
                    reset_ui_object_ids=("widget",),
                )
            },
            errors={},
        ),
    )
    payload = json.dumps(
        {"schema": 1, "runtime": runtime.to_dict()},
        separators=(",", ":"),
    ).encode()

    assert decode_runtime_response(payload) == runtime


def test_runtime_protocol_rejects_nonfinite_values() -> None:
    payload = (
        b'{"schema":1,"runtime":{"cells":{},"values":{"values":{"x":NaN},'
        b'"errors":{}},"outputs":{"outputs":{},"errors":{}}}}'
    )

    with pytest.raises(ProtocolError, match="invalid JSON"):
        decode_runtime_response(payload)


def test_runtime_protocol_rejects_excessive_nesting() -> None:
    payload = (
        b'{"schema":1,"runtime":{"cells":{},"values":{"values":{"x":'
        + b"[" * 100
        + b"0"
        + b"]" * 100
        + b'},"errors":{}},"outputs":{"outputs":{},"errors":{}}}}'
    )

    with pytest.raises(ProtocolError, match="invalid JSON"):
        decode_runtime_response(payload)


def test_runtime_protocol_json_depth_has_an_explicit_boundary() -> None:
    _validate_json_depth(_nested_value(64))

    with pytest.raises(ValueError, match="JSON exceeds 64 container levels"):
        _validate_json_depth(_nested_value(65))


def test_runtime_request_maps_excessive_nesting_to_a_protocol_error(
    tmp_path: Path,
) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema": 1,
                "notebook": str(tmp_path / "analysis.py"),
                "cellIds": [],
                "variables": [],
                "outputSelectorGroups": [],
                "showTracebacks": False,
                "timeout": 1,
                "valueMaxBytes": 1024,
                "sourceGeneration": _nested_value(100),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProtocolError, match="request is invalid") as raised:
        load_runtime_request(request)

    assert str(raised.value.__cause__) == "JSON exceeds 64 container levels"


def test_runtime_protocol_rejects_an_unbounded_timestamp() -> None:
    payload = {
        "schema": 1,
        "runtime": {
            "cells": {},
            "values": {"values": {}, "errors": {}},
            "outputs": {
                "outputs": {
                    "chart": {
                        "ownerCellId": "cell",
                        "mimetype": "text/html",
                        "data": "<div></div>",
                        "timestamp": 10**400,
                        "resetUiObjectIds": [],
                    }
                },
                "errors": {},
            },
        },
    }

    with pytest.raises(ProtocolError, match="invalid probe"):
        decode_runtime_response(json.dumps(payload).encode())
