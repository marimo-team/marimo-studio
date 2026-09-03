"""Run explicit notebook inspection in one supervised Python process."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._notebook.runtime_protocol import (
    decode_runtime_response,
    encode_runtime_request,
)
from marimo_studio._notebook.source_generation import NotebookSourceGeneration
from marimo_studio._processes.isolated_module import run_isolated_module_request
from marimo_studio._processes.limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    runtime_process_timeout,
)
from marimo_studio._processes.response_file import ProcessResponseError
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
    try:
        outcome = await run_isolated_module_request(
            "marimo_studio._notebook.runtime_worker",
            request,
            runtime_process_timeout(timeout),
            prefix="marimo-studio-runtime-",
        )
    except ProcessCleanupError:
        raise
    except ProcessResponseError as error:
        raise ProtocolError(f"Isolated notebook runtime {error}") from error
    except OSError as error:
        raise ProtocolError(
            f"Isolated notebook runtime could not start: {error}"
        ) from error
    return _decode_process_result(
        outcome.process,
        response=outcome.response,
        timeout=timeout,
    )


def _decode_process_result(
    result: ProcessResult,
    *,
    response: bytes | None,
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
    assert response is not None
    return decode_runtime_response(response)
