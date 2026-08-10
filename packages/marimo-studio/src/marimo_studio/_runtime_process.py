"""Run runtime validation outside a live Marimo server process."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Literal, cast

from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.types import CheckResult

_PROCESS_TIMEOUT = 75.0
_MAX_ERROR_CHARS = 4_000


async def check_runtime_studio_isolated(
    studio: StudioWorkspace,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Run Studio's runtime checks in a dedicated Python process."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "marimo_studio._runtime_process",
        str(studio.notebook),
        view_name or "",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_PROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await _terminate(process)
        return _process_failure(
            studio,
            f"Isolated notebook runtime exceeded {_PROCESS_TIMEOUT:g} seconds.",
        )
    except BaseException:
        await _terminate(process)
        raise

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail[-_MAX_ERROR_CHARS:]}" if detail else ""
        return _process_failure(
            studio,
            "Isolated notebook runtime exited with status "
            f"{process.returncode}{suffix}",
        )
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _process_failure(
            studio,
            "Isolated notebook runtime returned invalid JSON.",
        )
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or not isinstance(payload.get("checks"), list)
    ):
        return _process_failure(
            studio,
            "Isolated notebook runtime returned an invalid response.",
        )
    try:
        return tuple(_parse_check(item) for item in payload["checks"])
    except (TypeError, ValueError):
        return _process_failure(
            studio,
            "Isolated notebook runtime returned an invalid check.",
        )


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


def _process_failure(
    studio: StudioWorkspace,
    message: str,
) -> tuple[CheckResult, ...]:
    return (
        CheckResult(
            "runtime",
            "fail",
            message,
            code="runtime-check-failed",
            details={
                "source": {"path": str(studio.notebook)},
                "hint": (
                    "Run marimo-studio check with --runtime in the notebook "
                    "environment, fix the reported setup error, then rerun "
                    "the analysis."
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


def _run_worker(notebook: str, view_name: str) -> int:
    from marimo_studio._workspace import load_studio
    from marimo_studio.checks import check_runtime_studio

    studio = load_studio(Path(notebook))
    checks = asyncio.run(
        check_runtime_studio(
            studio,
            view_name=view_name or None,
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
    if len(sys.argv) != 3:
        raise SystemExit(2)
    raise SystemExit(_run_worker(sys.argv[1], sys.argv[2]))


__all__ = ["check_runtime_studio_isolated"]
