"""Protect the runtime-inspection worker record protocol."""

from __future__ import annotations

import json

import pytest

from marimo_studio._notebook.runtime_protocol import decode_runtime_response
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
        + b"[" * 1_500
        + b"0"
        + b"]" * 1_500
        + b'},"errors":{}},"outputs":{"outputs":{},"errors":{}}}}'
    )

    with pytest.raises(ProtocolError, match="invalid JSON"):
        decode_runtime_response(payload)


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
