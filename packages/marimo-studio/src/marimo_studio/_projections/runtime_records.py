"""Runtime value, output, and cell probe records."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

MAX_RUNTIME_VALUE_BYTES = 1_000_000


@dataclass(frozen=True)
class ValueReadError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ValueReadResult:
    values: dict[str, object]
    errors: dict[str, ValueReadError]

    def to_dict(self) -> dict[str, object]:
        return {
            "values": self.values,
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
        }


@dataclass(frozen=True)
class RenderedOutput:
    owner_cell_id: str
    mimetype: str
    data: str
    timestamp: float
    reset_ui_object_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "ownerCellId": self.owner_cell_id,
            "mimetype": self.mimetype,
            "data": self.data,
            "timestamp": self.timestamp,
            "resetUiObjectIds": list(self.reset_ui_object_ids),
        }


@dataclass(frozen=True)
class OutputRenderResult:
    outputs: dict[str, RenderedOutput]
    errors: dict[str, ValueReadError]
    overlays: dict[str, RenderedOutput] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "outputs": {
                selector: output.to_dict() for selector, output in self.outputs.items()
            },
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
            **(
                {
                    "overlays": {
                        name: output.to_dict() for name, output in self.overlays.items()
                    }
                }
                if self.overlays
                else {}
            ),
        }


@dataclass(frozen=True)
class RuntimeOutput:
    channel: str
    mimetype: str
    empty: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "mimetype": self.mimetype,
            "empty": self.empty,
        }


@dataclass(frozen=True)
class RuntimeCell:
    status: str | None
    outputs: tuple[RuntimeOutput, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "outputs": [output.to_dict() for output in self.outputs],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class RuntimeProbe:
    cells: dict[str, RuntimeCell]
    values: ValueReadResult
    outputs: OutputRenderResult

    def to_dict(self) -> dict[str, object]:
        return {
            "cells": {cell_id: cell.to_dict() for cell_id, cell in self.cells.items()},
            "values": self.values.to_dict(),
            "outputs": self.outputs.to_dict(),
        }


def runtime_probe_from_dict(value: object) -> RuntimeProbe:
    """Decode one runtime probe received from an owned worker."""
    payload = _exact_record(value, {"cells", "values", "outputs"})
    cells = _record(payload["cells"])
    return RuntimeProbe(
        cells={cell_id: _parse_cell(cell) for cell_id, cell in cells.items()},
        values=_parse_value_result(payload["values"]),
        outputs=_parse_output_result(payload["outputs"]),
    )


def _parse_cell(value: object) -> RuntimeCell:
    payload = _exact_record(value, {"status", "outputs", "errors"})
    status = payload["status"]
    outputs = payload["outputs"]
    errors = payload["errors"]
    if (
        (status is not None and not isinstance(status, str))
        or not isinstance(outputs, list)
        or not isinstance(errors, list)
    ):
        raise ValueError
    return RuntimeCell(
        status=status,
        outputs=tuple(_parse_runtime_output(output) for output in outputs),
        errors=tuple(_string(error) for error in errors),
    )


def _parse_runtime_output(value: object) -> RuntimeOutput:
    payload = _exact_record(value, {"channel", "mimetype", "empty"})
    empty = payload["empty"]
    if type(empty) is not bool:
        raise ValueError
    return RuntimeOutput(
        channel=_string(payload["channel"]),
        mimetype=_string(payload["mimetype"]),
        empty=empty,
    )


def _parse_value_result(value: object) -> ValueReadResult:
    payload = _exact_record(value, {"values", "errors"})
    values = _record(payload["values"])
    errors = _record(payload["errors"])
    return ValueReadResult(
        values=values,
        errors={
            selector: _parse_value_error(error) for selector, error in errors.items()
        },
    )


def _parse_value_error(value: object) -> ValueReadError:
    payload = _exact_record(value, {"code", "message"})
    return ValueReadError(
        code=_string(payload["code"]),
        message=_string(payload["message"]),
    )


def _parse_output_result(value: object) -> OutputRenderResult:
    payload = _record(value)
    if set(payload) not in ({"outputs", "errors"}, {"outputs", "errors", "overlays"}):
        raise ValueError
    outputs = _record(payload["outputs"])
    errors = _record(payload["errors"])
    return OutputRenderResult(
        outputs={
            selector: _parse_rendered_output(output)
            for selector, output in outputs.items()
        },
        overlays={
            name: _parse_rendered_output(output)
            for name, output in _record(payload.get("overlays", {})).items()
        },
        errors={
            selector: _parse_value_error(error) for selector, error in errors.items()
        },
    )


def _parse_rendered_output(value: object) -> RenderedOutput:
    payload = _exact_record(
        value,
        {"ownerCellId", "mimetype", "data", "timestamp", "resetUiObjectIds"},
    )
    timestamp = payload["timestamp"]
    reset_ids = payload["resetUiObjectIds"]
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not isinstance(reset_ids, list)
    ):
        raise ValueError
    try:
        finite_timestamp = math.isfinite(timestamp)
    except (OverflowError, ValueError):
        raise ValueError from None
    if not finite_timestamp:
        raise ValueError
    return RenderedOutput(
        owner_cell_id=_string(payload["ownerCellId"]),
        mimetype=_string(payload["mimetype"]),
        data=_string(payload["data"]),
        timestamp=float(timestamp),
        reset_ui_object_ids=tuple(_string(value) for value in reset_ids),
    )


def _record(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError
    return value


def _exact_record(value: object, fields: set[str]) -> dict[str, Any]:
    payload = _record(value)
    if set(payload) != fields:
        raise ValueError
    return payload


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value
