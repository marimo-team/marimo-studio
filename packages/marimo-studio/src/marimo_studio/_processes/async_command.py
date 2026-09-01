"""Run one supervised command through terminal cancellation cleanup."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from functools import partial

from marimo_studio._processes.ownership import settle_ownership
from marimo_studio._processes.provider_operation import find_process_cleanup_error
from marimo_studio._processes.supervisor import ProcessResult, ProcessSupervisor


async def run_supervised_command(
    command: Sequence[str],
    timeout: float,
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    owns_process_tree: bool = True,
) -> ProcessResult:
    """Run a command and finish owned cleanup before propagating cancellation."""
    supervisor = (
        ProcessSupervisor()
        if owns_process_tree
        else ProcessSupervisor(owns_process_tree=False)
    )
    operation = (
        partial(supervisor.run, list(command), timeout)
        if cwd is None and env is None
        else partial(
            supervisor.run,
            list(command),
            timeout,
            cwd=cwd,
            env=env,
        )
    )
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
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
