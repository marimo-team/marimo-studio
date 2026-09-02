"""Serve one runtime-inspection request inside a supervised process."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from marimo_studio._composition import create_worker_runtime_probe
from marimo_studio._notebook.runtime_protocol import (
    RUNTIME_PROTOCOL_SCHEMA,
    load_runtime_request,
)
from marimo_studio._notebook.source_generation import (
    require_notebook_source_generation,
)
from marimo_studio._processes.response_file import (
    MAX_PROCESS_RESPONSE_BYTES,
    write_process_response,
)
from marimo_studio.errors import ConfigurationError, ProtocolError, RuntimeTimeoutError


def _error_response(code: str, message: str) -> dict[str, object]:
    return {
        "schema": RUNTIME_PROTOCOL_SCHEMA,
        "error": {"code": code, "message": message},
    }


def _run_worker(request_path: Path, response_path: Path) -> int:
    try:
        request = load_runtime_request(request_path)
        notebook = Path(request["notebook"])
        source_generation = request["source_generation"]
        if source_generation is not None:
            require_notebook_source_generation(notebook, source_generation)
        runtime = asyncio.run(
            create_worker_runtime_probe()(
                notebook,
                cell_ids=request["cell_ids"],
                variables=request["variables"],
                output_selector_groups=request["output_selector_groups"],
                show_tracebacks=request["show_tracebacks"],
                timeout=request["timeout"],
                value_max_bytes=request["value_max_bytes"],
                source_generation=source_generation,
            )
        )
        response: dict[str, object] = {
            "schema": RUNTIME_PROTOCOL_SCHEMA,
            "runtime": runtime.to_dict(),
        }
    except RuntimeTimeoutError as error:
        response = _error_response(error.code, str(error))
    except ProtocolError as error:
        response = _error_response(error.code, str(error))
    except ConfigurationError as error:
        response = _error_response(error.code, str(error))
    encoded = json.dumps(
        response,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_PROCESS_RESPONSE_BYTES:
        encoded = json.dumps(
            _error_response(
                ProtocolError.code,
                "Notebook runtime inspection exceeded the response byte limit",
            ),
            separators=(",", ":"),
        ).encode("utf-8")
    write_process_response(response_path, encoded)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    exit_code = _run_worker(Path(sys.argv[1]), Path(sys.argv[2]))
    # The supervisor owns this process tree. Flush the protocol response before
    # bypassing interpreter waits for a lingering Marimo kernel thread.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
