"""Read and write one bounded response from an owned process."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._processes.supervisor import MAX_PROCESS_STDOUT_BYTES

MAX_PROCESS_RESPONSE_BYTES = MAX_PROCESS_STDOUT_BYTES


class ProcessResponseError(OSError):
    """An owned process response is missing, unreadable, or oversized."""


def write_process_response(path: Path, payload: bytes) -> None:
    """Write a complete bounded response for the supervising process."""
    if len(payload) > MAX_PROCESS_RESPONSE_BYTES:
        raise ProcessResponseError(
            f"Process response exceeds {MAX_PROCESS_RESPONSE_BYTES} bytes"
        )
    try:
        path.write_bytes(payload)
    except OSError as error:
        raise ProcessResponseError(
            f"Process response could not be written: {error}"
        ) from error


def read_process_response(path: Path) -> bytes:
    """Read a complete bounded response after its owned process exits."""
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_PROCESS_RESPONSE_BYTES + 1)
    except OSError as error:
        raise ProcessResponseError(
            f"Process response could not be read: {error}"
        ) from error
    if len(payload) > MAX_PROCESS_RESPONSE_BYTES:
        raise ProcessResponseError(
            f"Process response exceeds {MAX_PROCESS_RESPONSE_BYTES} bytes"
        )
    return payload
