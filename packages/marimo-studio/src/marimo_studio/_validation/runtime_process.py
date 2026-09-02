"""Run runtime validation outside a live Marimo server process."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from marimo_studio._processes.async_command import run_supervised_command
from marimo_studio._processes.limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    runtime_process_timeout,
    validate_runtime_timeout,
)
from marimo_studio._processes.provider_operation import (
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._processes.response_file import (
    ProcessResponseError,
    read_process_response,
    write_process_response,
)
from marimo_studio._processes.supervisor import (
    ProcessCleanupError,
    ProcessResult,
    process_returncode_message,
)
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.runtime_protocol import (
    encode_runtime_validation_request,
    load_runtime_validation_request,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError


async def check_runtime_studio_isolated(
    studio: StudioWorkspace,
    *,
    view_name: str | None = None,
    expected_revisions: dict[str, str] | None = None,
    timeout: float = DEFAULT_RUNTIME_TIMEOUT,
) -> tuple[CheckResult, ...]:
    """Run Studio's runtime checks in a supervised Python process."""
    validate_runtime_timeout(timeout)
    views: tuple[str, ...] = ()
    before: dict[str, str] | None = None
    if expected_revisions is not None:
        views = (view_name,) if view_name else tuple(studio.views)
        try:
            before = await run_provider_operation(
                partial(_source_revisions, studio, views)
            )
        except (KeyError, OSError, MarimoStudioError, ValueError) as error:
            raise_process_cleanup(error)
            return _process_failure(
                studio,
                f"Studio source revisions could not be captured: {error}",
            )
        if before != expected_revisions:
            return (_source_changed_check(studio.notebook),)
    process_timeout = runtime_process_timeout(timeout)
    try:
        request = encode_runtime_validation_request(
            studio.notebook,
            view_name,
            expected_revisions,
            timeout,
        )
    except ValueError as error:
        return _process_failure(
            studio,
            f"Isolated notebook runtime request is invalid: {error}",
        )
    try:
        result, response = await _run_runtime_worker(request, process_timeout)
    except ProcessCleanupError as error:
        if isinstance(error.__cause__, asyncio.CancelledError):
            raise
        return _process_failure(
            studio,
            f"Isolated notebook runtime cleanup failed: {error}",
            code="runtime-cleanup-failed",
            hint=(
                "Stop the remaining notebook processes, repair the host process "
                "cleanup failure, then rerun validation."
            ),
        )
    except ProcessResponseError as error:
        return _process_failure(
            studio,
            f"Isolated notebook runtime response is unavailable: {error}",
        )
    except OSError as error:
        return _process_failure(
            studio,
            f"Isolated notebook runtime could not start: {error}",
        )

    if result.timed_out:
        return _process_failure(
            studio,
            f"Isolated notebook runtime exceeded {process_timeout:g} seconds.",
            code="runtime-timeout",
            hint=(
                "Increase runtime_timeout for expected setup work, or fix the "
                "notebook operation that did not finish. The CLI option is "
                "--runtime-timeout."
            ),
        )
    if result.output_too_large:
        return _process_failure(
            studio,
            "Isolated notebook runtime returned more than 2 MB of output.",
        )
    if result.returncode != 0:
        failure = (
            f"Isolated notebook runtime {process_returncode_message(result.returncode)}"
        )
        return _process_failure(
            studio,
            failure,
        )
    try:
        payload = json.loads(response)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _process_failure(
            studio,
            "Isolated notebook runtime returned invalid JSON.",
        )
    if (
        not isinstance(payload, dict)
        or type(payload.get("schema")) is not int
        or payload.get("schema") != 1
        or not isinstance(payload.get("checks"), list)
    ):
        return _process_failure(
            studio,
            "Isolated notebook runtime returned an invalid response.",
        )
    try:
        checks = tuple(_parse_check(item) for item in payload["checks"])
    except (TypeError, ValueError):
        return _process_failure(
            studio,
            "Isolated notebook runtime returned an invalid check.",
        )
    if before is None:
        return checks
    try:
        after = await run_provider_operation(partial(_source_revisions, studio, views))
    except (KeyError, OSError, MarimoStudioError, ValueError) as error:
        raise_process_cleanup(error)
        return (
            *checks,
            *_process_failure(
                studio,
                f"Studio source revisions could not be recaptured: {error}",
            ),
        )
    return (
        *checks,
        *((_source_changed_check(studio.notebook),) if before != after else ()),
    )


async def _run_runtime_worker(
    request: bytes,
    timeout: float,
) -> tuple[ProcessResult, bytes]:
    with tempfile.TemporaryDirectory(prefix="marimo-studio-validation-") as root:
        request_path = Path(root) / "request.json"
        response_path = Path(root) / "response.json"
        request_path.write_bytes(request)
        result = await run_supervised_command(
            [
                sys.executable,
                "-m",
                "marimo_studio._validation.runtime_process",
                str(request_path),
                str(response_path),
            ],
            timeout,
        )
        response = (
            read_process_response(response_path)
            if not result.timed_out
            and not result.output_too_large
            and result.returncode == 0
            else b""
        )
    return result, response


def _process_failure(
    studio: StudioWorkspace,
    message: str,
    *,
    code: str = "runtime-check-failed",
    hint: str | None = None,
) -> tuple[CheckResult, ...]:
    return (
        CheckResult(
            "runtime",
            "fail",
            message,
            code=code,
            details={
                "source": {"path": str(studio.notebook)},
                "hint": hint
                or (
                    f"Run marimo-studio validate --target {studio.notebook} "
                    "--level runtime "
                    "in the notebook environment, fix the reported setup error, "
                    "then rerun validation."
                ),
            },
        ),
    )


def _parse_check(value: object) -> CheckResult:
    if not isinstance(value, dict):
        raise TypeError
    name = value.get("name")
    status = value.get("status")
    message = value.get("message")
    code = value.get("code")
    details = value.get("details")
    if (
        not isinstance(name, str)
        or status not in {"pass", "warn", "fail"}
        or not isinstance(message, str)
        or (code is not None and not isinstance(code, str))
        or (
            details is not None
            and (
                not isinstance(details, dict)
                or not all(isinstance(key, str) for key in details)
            )
        )
    ):
        raise ValueError
    return CheckResult(
        name=name,
        status=cast(Literal["pass", "warn", "fail"], status),
        message=message,
        code=code,
        details=cast(dict[str, Any] | None, details),
    )


def _source_revisions(
    studio: StudioWorkspace,
    views: tuple[str, ...],
) -> dict[str, str]:
    from marimo_studio._views.revisions import capture_source_revisions

    return capture_source_revisions(studio, views)


def _source_changed_check(notebook: Path) -> CheckResult:
    return CheckResult(
        "validation-source-revision",
        "fail",
        "Studio sources changed before runtime validation completed.",
        code="validation-source-changed",
        details={
            "source": {"path": str(notebook)},
            "hint": "Wait for the current edits to save, then rerun validation.",
        },
    )


def _run_worker(
    request_path: Path,
    response_path: Path,
) -> int:
    from marimo_studio._validation.static import check_runtime_studio
    from marimo_studio._workspace import load_studio

    request = load_runtime_validation_request(request_path)
    path = request.notebook
    timeout = request.timeout
    studio = load_studio(path)
    views = (
        (request.view_name,) if request.view_name is not None else tuple(studio.views)
    )
    from marimo_studio._views.revisions import capture_published_presentations

    expected = request.expected_revisions
    if expected is not None and _source_revisions(studio, views) != expected:
        checks = (_source_changed_check(path),)
    else:
        snapshot = capture_published_presentations(studio, views)
        if snapshot is None:
            checks = _process_failure(
                studio,
                "Published presentations are unavailable for runtime validation.",
            )
        else:
            with snapshot:
                mounts = {name: snapshot.artifacts[name].mounts for name in views}
            checks = asyncio.run(
                check_runtime_studio(
                    studio,
                    view_name=request.view_name,
                    timeout=timeout,
                    _published_mounts=mounts,
                )
            )
            if expected is not None and _source_revisions(studio, views) != expected:
                checks = (*checks, _source_changed_check(path))
    write_process_response(
        response_path,
        json.dumps(
            {
                "schema": 1,
                "checks": [check.to_dict() for check in checks],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    exit_code = _run_worker(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
    )
    # The supervisor owns this isolated process group. Flush the protocol
    # response before bypassing interpreter waits for a lingering kernel thread.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
