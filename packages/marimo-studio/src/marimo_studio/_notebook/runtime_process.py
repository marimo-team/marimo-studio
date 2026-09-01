"""Run explicit notebook inspection in one supervised Python process."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from marimo_studio._notebook.runtime_protocol import (
    decode_runtime_response,
    encode_runtime_request,
)
from marimo_studio._notebook.source_generation import NotebookSourceGeneration
from marimo_studio._processes.async_command import run_supervised_command
from marimo_studio._processes.limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    runtime_process_timeout,
)
from marimo_studio._processes.response_file import (
    ProcessResponseError,
    read_process_response,
)
from marimo_studio._processes.supervisor import (
    ProcessCleanupError,
    ProcessResult,
    process_returncode_message,
)
from marimo_studio._projections.runtime_records import RuntimeProbe
from marimo_studio.errors import ProtocolError, RuntimeTimeoutError


async def probe_runtime_isolated(
    path: Path,
    *,
    cell_ids: tuple[str, ...],
    variables: tuple[str, ...],
    output_selector_groups: tuple[tuple[str, ...], ...],
    show_tracebacks: bool,
    timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    value_max_bytes: int | None = None,
    source_generation: NotebookSourceGeneration | None = None,
) -> RuntimeProbe:
    """Run a notebook probe in a supervised process and decode its result."""
    request = encode_runtime_request(
        path,
        cell_ids=cell_ids,
        variables=variables,
        output_selector_groups=output_selector_groups,
        show_tracebacks=show_tracebacks,
        timeout=timeout,
        value_max_bytes=value_max_bytes,
        source_generation=source_generation,
    )
    with tempfile.TemporaryDirectory(prefix="marimo-studio-runtime-") as root:
        request_path = Path(root) / "request.json"
        response_path = Path(root) / "response.json"
        request_path.write_bytes(request)
        try:
            result = await run_supervised_command(
                [
                    sys.executable,
                    "-m",
                    "marimo_studio._notebook.runtime_worker",
                    str(request_path),
                    str(response_path),
                ],
                runtime_process_timeout(timeout),
            )
        except ProcessCleanupError:
            raise
        except OSError as error:
            raise ProtocolError(
                f"Isolated notebook runtime could not start: {error}"
            ) from error
        return _decode_process_result(
            result,
            response_path=response_path,
            timeout=timeout,
        )


def _decode_process_result(
    result: ProcessResult,
    *,
    response_path: Path,
    timeout: float,
) -> RuntimeProbe:
    if result.timed_out:
        raise RuntimeTimeoutError(
            f"Notebook runtime inspection exceeded {timeout:g} seconds"
        )
    if result.output_too_large:
        raise ProtocolError("Isolated notebook runtime emitted too much process output")
    if result.returncode != 0:
        raise ProtocolError(
            f"Isolated notebook runtime {process_returncode_message(result.returncode)}"
        )
    try:
        payload = read_process_response(response_path)
    except ProcessResponseError as error:
        raise ProtocolError(f"Isolated notebook runtime {error}") from error
    return decode_runtime_response(payload)
