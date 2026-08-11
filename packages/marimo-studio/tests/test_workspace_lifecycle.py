from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from marimo_studio._server.workspace_lifecycle import (
    Invalid,
    NeedsView,
    Ready,
    Unconfigured,
    resolve_workspace_lifecycle,
)
from marimo_studio.errors import ConfigurationError, WorkspaceInitializationError


def presentation(
    notebook: Path,
    *,
    definition: object | None = None,
    workspace: object | None = None,
    discover_error: Exception | None = None,
    materialize_error: Exception | None = None,
) -> Any:
    def discover_definition() -> object | None:
        if discover_error is not None:
            raise discover_error
        return definition

    def materialize(_definition: object) -> object:
        if materialize_error is not None:
            raise materialize_error
        return workspace

    return SimpleNamespace(
        notebook=notebook,
        discover_definition=discover_definition,
        materialize=materialize,
    )


def test_unconfigured_lifecycle_carries_the_notebook_identity(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"

    lifecycle = resolve_workspace_lifecycle(presentation(notebook))

    assert lifecycle == Unconfigured(notebook)


def test_needs_view_lifecycle_preserves_definition_and_error(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    definition = object()
    error = WorkspaceInitializationError("dashboard")

    lifecycle = resolve_workspace_lifecycle(
        presentation(
            notebook,
            definition=definition,
            materialize_error=error,
        )
    )

    assert isinstance(lifecycle, NeedsView)
    assert lifecycle.definition is definition
    assert lifecycle.error is error


def test_ready_lifecycle_carries_one_materialized_workspace(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    definition = object()
    workspace = object()

    lifecycle = resolve_workspace_lifecycle(
        presentation(notebook, definition=definition, workspace=workspace)
    )

    assert isinstance(lifecycle, Ready)
    assert lifecycle.definition is definition
    assert lifecycle.workspace is workspace


@pytest.mark.parametrize("phase", ["discovery", "materialization"])
def test_invalid_lifecycle_preserves_expected_failure(
    tmp_path: Path,
    phase: str,
) -> None:
    notebook = tmp_path / "analysis.py"
    definition = object()
    error = ConfigurationError("invalid configuration")
    lifecycle = resolve_workspace_lifecycle(
        presentation(
            notebook,
            definition=definition,
            discover_error=error if phase == "discovery" else None,
            materialize_error=error if phase == "materialization" else None,
        )
    )

    assert isinstance(lifecycle, Invalid)
    assert lifecycle.error is error
    assert lifecycle.definition is (definition if phase == "materialization" else None)


def test_workspace_lifecycle_propagates_unexpected_failures(tmp_path: Path) -> None:
    error = RuntimeError("programming defect")

    with pytest.raises(RuntimeError) as raised:
        resolve_workspace_lifecycle(
            presentation(tmp_path / "analysis.py", discover_error=error)
        )

    assert raised.value is error
