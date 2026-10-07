"""Private protocol for correlating Marimo kernel execution batches."""

from __future__ import annotations

from typing import Literal, cast

_PREFIX = "marimo-studio-execution"
_OBSERVATION_TOKEN_PREFIX = "observation:"
_OBSERVATION_FUNCTIONS = frozenset(
    {"execution_barrier", "read_values", "render_values", "sync_query"}
)
_COMPATIBILITY_COMPLETION_COMMANDS = frozenset(
    {
        "CreateNotebookCommand",
        "ExecuteCellsCommand",
        "ExecuteStaleCellsCommand",
        "InstallPackagesCommand",
        "SyncGraphCommand",
        "UpdateUIElementCommand",
    }
)

# These commands can mutate the notebook runtime before a CellNotification is
# emitted. Keep the list here so the server and kernel use the same boundary.
_EXECUTION_COMMANDS = frozenset(
    {
        "CreateNotebookCommand",
        "DeleteCellCommand",
        "ExecuteCellsCommand",
        "ExecuteStaleCellsCommand",
        "InstallPackagesCommand",
        "InvokeFunctionCommand",
        "ModelCommand",
        "RenameNotebookCommand",
        "SyncGraphCommand",
        "UpdateCellConfigCommand",
        "UpdateUIElementCommand",
    }
)


def is_execution_command(name: str) -> bool:
    return name in _EXECUTION_COMMANDS


def has_compatibility_completion(name: str) -> bool:
    return name in _COMPATIBILITY_COMPLETION_COMMANDS


def is_observation_command(request: object) -> bool:
    return (
        type(request).__name__ == "InvokeFunctionCommand"
        and getattr(request, "function_name", None) in _OBSERVATION_FUNCTIONS
    )


def is_observation_token(token: str) -> bool:
    return token.startswith(_OBSERVATION_TOKEN_PREFIX)


def make_marker(
    phase: Literal["start", "done", "failed"],
    name: str,
    token: str,
) -> str:
    return f"{_PREFIX}:{phase}:{name}:{token}"


def parse_marker(
    run_id: object,
) -> tuple[Literal["start", "done", "failed"], str, str] | None:
    if not isinstance(run_id, str):
        return None
    prefix, separator, remainder = run_id.partition(":")
    if prefix != _PREFIX or not separator:
        return None
    phase, separator, remainder = remainder.partition(":")
    if phase not in {"start", "done", "failed"} or not separator:
        return None
    name, separator, token = remainder.partition(":")
    if not separator or not is_execution_command(name) or not token:
        return None
    return cast(
        tuple[Literal["start", "done", "failed"], str, str],
        (phase, name, token),
    )
