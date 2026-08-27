"""Run runtime validation outside a live Marimo server process."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import sys
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from marimo_studio._processes.limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    MAX_RUNTIME_TIMEOUT,
    runtime_process_timeout,
)
from marimo_studio._processes.ownership import settle_ownership
from marimo_studio._processes.provider_operation import (
    find_process_cleanup_error,
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessSupervisor
from marimo_studio._validation.results import CheckResult
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
    if not math.isfinite(timeout) or not 0 <= timeout <= MAX_RUNTIME_TIMEOUT:
        raise ValueError(
            f"timeout must be a finite number between 0 and {MAX_RUNTIME_TIMEOUT:g}"
        )
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
    supervisor = ProcessSupervisor()
    process_timeout = runtime_process_timeout(timeout)
    command = [
        sys.executable,
        "-m",
        "marimo_studio._validation.runtime_process",
        str(studio.notebook),
        view_name or "",
        json.dumps(expected_revisions or {}, separators=(",", ":")),
        f"{timeout:.17g}",
    ]
    task = asyncio.create_task(
        asyncio.to_thread(supervisor.run, command, process_timeout)
    )
    try:
        result = await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        supervisor.cancel()
        try:
            await settle_ownership(task)
        except BaseException as error:
            cleanup = find_process_cleanup_error(error)
            if cleanup is not None:
                raise cleanup from cancellation
            raise cancellation from error
        raise cancellation
    except ProcessCleanupError as error:
        return _process_failure(
            studio,
            f"Isolated notebook runtime cleanup failed: {error}",
            code="runtime-cleanup-failed",
            hint=(
                "Stop the remaining notebook processes, repair the host process "
                "cleanup failure, then rerun validation."
            ),
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
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        failure = f"Isolated notebook runtime {_returncode_message(result.returncode)}"
        return _process_failure(
            studio,
            f"{failure}{suffix}",
        )
    try:
        payload = json.loads(result.stdout)
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


def _returncode_message(returncode: int, *, platform: str = os.name) -> str:
    if returncode >= 0:
        return f"exited with status {returncode}"
    if platform != "posix":
        return f"exited with status 0x{returncode & 0xFFFFFFFF:08X}"
    try:
        name = signal.Signals(-returncode).name
    except ValueError:
        name = str(-returncode)
    return f"was terminated by signal {name}"


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
        "analysis-source-revision",
        "fail",
        "Studio sources changed before runtime validation completed.",
        code="analysis-source-changed",
        details={
            "source": {"path": str(notebook)},
            "hint": "Wait for the current edits to save, then rerun validation.",
        },
    )


def _run_worker(
    notebook: str,
    view_name: str,
    expected_json: str,
    timeout_text: str,
) -> int:
    from marimo_studio._validation.static import check_runtime_studio
    from marimo_studio._workspace import load_studio

    path = Path(notebook)
    timeout = float(timeout_text)
    if not math.isfinite(timeout) or not 0 <= timeout <= MAX_RUNTIME_TIMEOUT:
        raise ValueError("Runtime timeout is outside the supported range")
    expected_value = json.loads(expected_json)
    if not isinstance(expected_value, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in expected_value.items()
    ):
        raise ValueError("Expected revisions must be a string mapping")
    studio = load_studio(path)
    views = (view_name,) if view_name else tuple(studio.views)
    from marimo_studio._views.revisions import capture_published_presentations

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
                view_name=view_name or None,
                timeout=timeout,
                _published_mounts=mounts,
            )
        )
    sys.stdout.write(
        json.dumps(
            {
                "schema": 1,
                "checks": [check.to_dict() for check in checks],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(2)
    exit_code = _run_worker(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    # The supervisor owns this isolated process group. Flush the protocol
    # response before bypassing interpreter waits for a lingering kernel thread.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
