"""Protect the bounded runtime-validation worker request."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from marimo_studio._validation.runtime_protocol import (
    MAX_RUNTIME_VALIDATION_REQUEST_BYTES,
    encode_runtime_validation_request,
    load_runtime_validation_request,
)
from marimo_studio.errors import ProtocolError


def _long_revisions(count: int) -> dict[str, str]:
    return {
        f"{index:04x}" + "v" * 236: hashlib.sha256(str(index).encode()).hexdigest()
        for index in range(count)
    }


def test_runtime_validation_request_round_trips_many_maximum_view_names(
    tmp_path: Path,
) -> None:
    revisions = _long_revisions(1_000)
    encoded = encode_runtime_validation_request(
        tmp_path / "analysis.py",
        None,
        revisions,
        42,
    )
    request_path = tmp_path / "request.json"
    request_path.write_bytes(encoded)

    request = load_runtime_validation_request(request_path)

    assert len(encoded) < MAX_RUNTIME_VALIDATION_REQUEST_BYTES
    assert request.notebook == tmp_path / "analysis.py"
    assert request.view_name is None
    assert request.expected_revisions == revisions
    assert request.timeout == 42


def test_runtime_validation_request_rejects_an_oversized_mapping(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="request exceeds"):
        encode_runtime_validation_request(
            tmp_path / "analysis.py",
            None,
            _long_revisions(2_000),
            42,
        )


@pytest.mark.parametrize(
    "payload",
    (
        b"{",
        b'{"schema":1}',
        json.dumps(
            {
                "schema": 2,
                "notebook": "analysis.py",
                "view": None,
                "expectedRevisions": None,
                "timeout": 42,
            }
        ).encode(),
        json.dumps(
            {
                "schema": 1,
                "notebook": "analysis.py",
                "view": None,
                "expectedRevisions": {"dashboard": "not-a-revision"},
                "timeout": 42,
            }
        ).encode(),
    ),
)
def test_runtime_validation_request_rejects_malformed_payloads(
    tmp_path: Path,
    payload: bytes,
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_bytes(payload)

    with pytest.raises(ProtocolError, match="Runtime validation request"):
        load_runtime_validation_request(request_path)


def test_runtime_validation_request_rejects_an_oversized_file(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_bytes(b"x" * (MAX_RUNTIME_VALIDATION_REQUEST_BYTES + 1))

    with pytest.raises(ProtocolError, match="request exceeds"):
        load_runtime_validation_request(request_path)
