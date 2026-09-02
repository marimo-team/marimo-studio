"""Exchange one bounded request with an isolated Python module."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from marimo_studio._processes.async_command import run_supervised_command
from marimo_studio._processes.ownership import settle_ownership
from marimo_studio._processes.response_file import (
    MAX_PROCESS_RESPONSE_BYTES,
    read_process_response,
)
from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessResult

MAX_PROCESS_REQUEST_BYTES = MAX_PROCESS_RESPONSE_BYTES


class ProcessRequestError(OSError):
    """An isolated module request is unwritable or exceeds its byte budget."""


@dataclass(frozen=True)
class IsolatedModuleResult:
    """The process outcome and its optional successful response."""

    process: ProcessResult
    response: bytes | None


@dataclass(frozen=True)
class _RequestWorkspace:
    directory: TemporaryDirectory[str]
    request_path: Path
    response_path: Path


async def run_isolated_module_request(
    module: str,
    request: bytes,
    timeout: float,
    *,
    prefix: str,
) -> IsolatedModuleResult:
    """Run ``module`` with private request and response file arguments."""
    setup = asyncio.create_task(
        asyncio.to_thread(_prepare_request_workspace, request, prefix)
    )
    workspace, cancellation = await settle_ownership(setup)
    if cancellation is not None:
        await _cleanup_request_workspace(workspace)
        raise cancellation

    result: ProcessResult | None = None
    response: bytes | None = None
    try:
        try:
            result = await run_supervised_command(
                [
                    sys.executable,
                    "-m",
                    module,
                    str(workspace.request_path),
                    str(workspace.response_path),
                ],
                timeout,
            )
        except asyncio.CancelledError as error:
            cancellation = error
        else:
            if _has_response(result):
                reading = asyncio.create_task(
                    asyncio.to_thread(read_process_response, workspace.response_path)
                )
                response, read_cancellation = await settle_ownership(reading)
                cancellation = cancellation or read_cancellation
    finally:
        cleanup_cancellation = await _cleanup_request_workspace(workspace)
        cancellation = cancellation or cleanup_cancellation

    if cancellation is not None:
        raise cancellation
    assert result is not None
    return IsolatedModuleResult(process=result, response=response)


def _prepare_request_workspace(request: bytes, prefix: str) -> _RequestWorkspace:
    if len(request) > MAX_PROCESS_REQUEST_BYTES:
        raise ProcessRequestError(
            f"Process request exceeds {MAX_PROCESS_REQUEST_BYTES} bytes"
        )
    directory = TemporaryDirectory(prefix=prefix)
    request_path = Path(directory.name) / "request.json"
    response_path = Path(directory.name) / "response.json"
    try:
        request_path.write_bytes(request)
    except OSError as error:
        directory.cleanup()
        raise ProcessRequestError(
            f"Process request could not be written: {error}"
        ) from error
    return _RequestWorkspace(directory, request_path, response_path)


async def _cleanup_request_workspace(
    workspace: _RequestWorkspace,
) -> asyncio.CancelledError | None:
    cleanup = asyncio.create_task(
        asyncio.to_thread(_remove_request_workspace, workspace)
    )
    try:
        _, cancellation = await settle_ownership(cleanup)
    except OSError as error:
        raise ProcessCleanupError(
            f"Isolated module request cleanup failed: {error}"
        ) from error
    return cancellation


def _remove_request_workspace(workspace: _RequestWorkspace) -> None:
    workspace.directory.cleanup()


def _has_response(result: ProcessResult) -> bool:
    return (
        not result.timed_out and not result.output_too_large and result.returncode == 0
    )
