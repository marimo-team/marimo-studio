"""Retire one served view name across server lifecycles.

Removing or renaming a view retires its name. The server drains the name's
development work and releases its artifact pins before the workspace commit
moves or deletes the view project.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership_outcome,
)
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.remove import delete_view
from marimo_studio._views.rename import rename_view
from marimo_studio._workspace.config import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    view_retirement_lock,
    workspace_catalog_lock,
)
from marimo_studio.errors import (
    ViewDeletionError,
    ViewGenerationConflictError,
    WorkspaceGenerationConflictError,
)
from marimo_studio.errors._internal import ViewRetirementCapacityError

_MAX_RETIREMENT_THREADS = 8
_RETIREMENT_SLOTS = threading.BoundedSemaphore(_MAX_RETIREMENT_THREADS)


@dataclass(frozen=True)
class RetiredView:
    """The committed workspace and optional retained cleanup tree."""

    workspace: StudioWorkspace
    cleanup: Path | None = None


# Commit the workspace change for a retired name. It runs on a dedicated
# thread after the server released every owner of that name.
RetirementCommit = Callable[[StudioWorkspace], RetiredView]


@dataclass(frozen=True)
class _RetirementClaim:
    worker: asyncio.Future[RetiredView | None]
    claimed: asyncio.Event
    proceed: threading.Event
    abort: threading.Event


def validate_view_owner(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
) -> StudioWorkspace:
    """Return the current workspace when the caller still owns both generations."""
    current = load_studio(studio.config_path)
    generation = current.view_generations.get(name)
    if current.catalog_generation != expected_catalog_generation:
        raise WorkspaceGenerationConflictError()
    if generation != expected_generation:
        raise ViewGenerationConflictError(name, generation)
    return current


def _start_retirement_claim(
    studio: StudioWorkspace,
    name: str,
    commit: RetirementCommit,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
) -> _RetirementClaim:
    loop = asyncio.get_running_loop()
    slots = _RETIREMENT_SLOTS
    if not slots.acquire(blocking=False):
        raise ViewRetirementCapacityError()
    try:
        worker: asyncio.Future[RetiredView | None] = loop.create_future()
        claimed = asyncio.Event()
        proceed = threading.Event()
        abort = threading.Event()

        def retire() -> RetiredView | None:
            with workspace_catalog_lock(studio.view_root):
                _ = validate_view_owner(
                    studio,
                    name,
                    expected_catalog_generation=expected_catalog_generation,
                    expected_generation=expected_generation,
                )
            loop.call_soon_threadsafe(claimed.set)
            proceed.wait()
            if abort.is_set():
                return None
            with (
                presentation.retiring_view(name) as release_artifacts,
                view_retirement_lock(studio.view_root, name),
            ):
                current = validate_view_owner(
                    studio,
                    name,
                    expected_catalog_generation=expected_catalog_generation,
                    expected_generation=expected_generation,
                )
                release_artifacts()
                return commit(current)

        def complete() -> None:
            result: RetiredView | None = None
            failure: BaseException | None = None
            try:
                result = retire()
            except BaseException as error:
                failure = error
            finally:
                slots.release()
            if failure is not None:
                loop.call_soon_threadsafe(worker.set_exception, failure)
            else:
                loop.call_soon_threadsafe(worker.set_result, result)

        thread = threading.Thread(
            target=complete,
            name=f"marimo-studio-retire-{name}",
            daemon=True,
        )
        thread.start()
    except BaseException:
        slots.release()
        raise
    return _RetirementClaim(worker, claimed, proceed, abort)


async def _wait_for_claim(claim: _RetirementClaim) -> None:
    claimed = asyncio.create_task(claim.claimed.wait())
    done, _pending = await asyncio.wait(
        (claimed, claim.worker),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if claim.worker in done:
        claimed.cancel()
        await asyncio.gather(claimed, return_exceptions=True)
        result = claim.worker.result()
        if result is not None:
            raise RuntimeError("View retirement finished before its owner was claimed")
        return
    await claimed


async def _drain_claim(claim: _RetirementClaim) -> None:
    claim.abort.set()
    claim.proceed.set()
    await settle_ownership_outcome(claim.worker)


async def _coordinate_retirement(
    studio: StudioWorkspace,
    name: str,
    commit: RetirementCommit,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    claim = _start_retirement_claim(
        studio,
        name,
        commit,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
        presentation=presentation,
    )
    entered_development = False
    try:
        await _wait_for_claim(claim)
        async with development.retiring_view(name):
            entered_development = True
            claim.proceed.set()
            retired = await claim.worker
            if retired is None:
                raise RuntimeError("View retirement owner was released before commit")
            return retired
    finally:
        if not entered_development:
            await _drain_claim(claim)


async def retire_owned_view(
    studio: StudioWorkspace,
    name: str,
    commit: RetirementCommit,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    """Commit a change that retires one observed view name.

    The server drains every owner of the name first. A commit failure leaves
    the name in service.
    """
    result, failure, cancellation = await settle_ownership_outcome(
        _coordinate_retirement(
            studio,
            name,
            commit,
            expected_catalog_generation=expected_catalog_generation,
            expected_generation=expected_generation,
            presentation=presentation,
            development=development,
        )
    )
    if failure is not None:
        raise failure
    propagate_cancellation(cancellation)
    if result is None:
        raise RuntimeError("View retirement did not produce a terminal result")
    return result


async def delete_owned_view(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    """Delete one observed view after draining every server-side owner."""

    def delete(current: StudioWorkspace) -> RetiredView:
        try:
            return RetiredView(
                delete_view(
                    current,
                    name,
                    expected_catalog_generation=expected_catalog_generation,
                    expected_generation=expected_generation,
                )
            )
        except ViewDeletionError as error:
            # The catalog committed, and only cleanup of the old tree failed.
            if error.cleanup is None or not isinstance(
                error.committed_workspace,
                StudioWorkspace,
            ):
                raise
            return RetiredView(error.committed_workspace, cleanup=error.cleanup)

    return await retire_owned_view(
        studio,
        name,
        delete,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
        presentation=presentation,
        development=development,
    )


async def rename_owned_view(
    studio: StudioWorkspace,
    name: str,
    new_name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    """Rename one observed view after draining every server-side owner."""

    def rename(current: StudioWorkspace) -> RetiredView:
        return RetiredView(
            rename_view(
                current,
                name,
                new_name,
                expected_catalog_generation=expected_catalog_generation,
                expected_generation=expected_generation,
            )
        )

    return await retire_owned_view(
        studio,
        name,
        rename,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
        presentation=presentation,
        development=development,
    )
