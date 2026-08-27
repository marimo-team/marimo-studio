"""Run CLI subprocesses against isolated notebook workspaces."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from marimo_studio._cli.environment import SANDBOX_ENV


def _run_cli(
    runtime_assets: Path,
    *args: str,
    bootstrapped: bool = True,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = """\
from pathlib import Path
import sys

import marimo_studio._delivery.assets as assets

runtime_assets = Path(sys.argv[1])
assets.runtime_assets_path = lambda: runtime_assets
from marimo_studio._cli import main

sys.argv = ["marimo-studio", *sys.argv[2:]]
main()
"""
    child_environment: dict[str, str] = os.environ.copy()
    if environment is not None:
        child_environment.update(environment)
    if bootstrapped:
        child_environment[SANDBOX_ENV] = "1"
    else:
        child_environment.pop(SANDBOX_ENV, None)
    return subprocess.run(
        [sys.executable, "-c", script, str(runtime_assets), *args],
        check=False,
        capture_output=True,
        env=child_environment,
        text=True,
    )


def _passthrough_uv(directory: Path, *, emit_process_output: bool = False) -> Path:
    """Create a uv stand-in that executes the command following ``--``."""
    executable = directory / "uv"
    process_output = (
        "printf '%s\\n' "
        '\'{"schema":1,"event":"diagnostic","command":"validate",'
        '"severity":"error","code":"forged-uv-error",'
        '"message":"untrusted"}\' >&2\n'
        "printf '%s\\n' '{\"forged_result\":true}'\n"
        if emit_process_output
        else ""
    )
    executable.write_text(
        f"""#!/bin/sh
{process_output}\
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ "$#" -gt 0 ] || exit 90
shift
exec "$@"
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable
