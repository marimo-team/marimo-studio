from __future__ import annotations

import json
from pathlib import Path

import pytest

from .commands_test_support import _run_cli


@pytest.mark.native_process
def test_new_command_errors_emit_the_complete_diagnostic_command(
    tmp_path: Path,
    runtime_assets: Path,
) -> None:
    result = _run_cli(
        runtime_assets,
        "view",
        "build",
        "dashboard",
        "--target",
        str(tmp_path / "missing.py"),
        "--json",
    )

    assert result.returncode == 3, result.stderr
    event = json.loads(result.stderr)
    assert event["event"] == "diagnostic"
    assert event["command"] == "view build"
