"""Encode bounded requests for isolated runtime validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._processes.limits import validate_runtime_timeout
from marimo_studio.errors import ProtocolError

RUNTIME_VALIDATION_REQUEST_SCHEMA = 1
MAX_RUNTIME_VALIDATION_REQUEST_BYTES = 512 * 1024
_REQUEST_FIELDS = {
    "schema",
    "notebook",
    "view",
    "expectedRevisions",
    "timeout",
}


@dataclass(frozen=True)
class RuntimeValidationRequest:
    notebook: Path
    view_name: str | None
    expected_revisions: dict[str, str] | None
    timeout: float


def encode_runtime_validation_request(
    notebook: Path,
    view_name: str | None,
    expected_revisions: dict[str, str] | None,
    timeout: float,
) -> bytes:
    """Encode one validated runtime request within the worker byte budget."""
    validate_runtime_timeout(timeout)
    _validate_view_name(view_name)
    _validate_revisions(expected_revisions)
    encoded = json.dumps(
        {
            "schema": RUNTIME_VALIDATION_REQUEST_SCHEMA,
            "notebook": str(notebook),
            "view": view_name,
            "expectedRevisions": expected_revisions,
            "timeout": timeout,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_RUNTIME_VALIDATION_REQUEST_BYTES:
        raise ValueError(
            "runtime validation request exceeds "
            f"{MAX_RUNTIME_VALIDATION_REQUEST_BYTES} bytes"
        )
    return encoded


def load_runtime_validation_request(path: Path) -> RuntimeValidationRequest:
    """Decode one exact worker request from its private temporary file."""
    try:
        with path.open("rb") as stream:
            encoded = stream.read(MAX_RUNTIME_VALIDATION_REQUEST_BYTES + 1)
    except OSError as error:
        raise ProtocolError(
            f"Runtime validation request could not be read: {error}"
        ) from error
    if len(encoded) > MAX_RUNTIME_VALIDATION_REQUEST_BYTES:
        raise ProtocolError(
            "Runtime validation request exceeds "
            f"{MAX_RUNTIME_VALIDATION_REQUEST_BYTES} bytes"
        )
    try:
        value = json.loads(encoded)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise ProtocolError("Runtime validation request is invalid JSON") from error
    if not isinstance(value, dict) or set(value) != _REQUEST_FIELDS:
        raise ProtocolError("Runtime validation request has an invalid schema")
    if (
        value.get("schema") != RUNTIME_VALIDATION_REQUEST_SCHEMA
        or type(value.get("schema")) is not int
    ):
        raise ProtocolError("Runtime validation request has an invalid schema")
    notebook = value.get("notebook")
    view_name = value.get("view")
    expected_revisions = value.get("expectedRevisions")
    timeout = value.get("timeout")
    if not isinstance(notebook, str) or not notebook:
        raise ProtocolError("Runtime validation request has an invalid notebook")
    try:
        _validate_view_name(view_name)
        _validate_revisions(expected_revisions)
        validate_runtime_timeout(timeout)
    except ValueError as error:
        raise ProtocolError(
            "Runtime validation request has an invalid field"
        ) from error
    assert isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
    return RuntimeValidationRequest(
        notebook=Path(notebook),
        view_name=view_name,
        expected_revisions=expected_revisions,
        timeout=float(timeout),
    )


def _validate_view_name(value: object) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError("view_name must be a non-empty string or None")


def _validate_revisions(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or not all(
        isinstance(key, str)
        and key
        and isinstance(revision, str)
        and len(revision) == 64
        and all(character in "0123456789abcdef" for character in revision)
        for key, revision in value.items()
    ):
        raise ValueError("expected_revisions must contain SHA-256 revisions")
