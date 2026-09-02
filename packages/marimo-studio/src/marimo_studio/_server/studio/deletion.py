"""Coordinate one owned view deletion across server lifecycles."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership_outcome,
)
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.remove import delete_view, validate_view_deletion_owner
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio.errors import ViewDeletionError
from marimo_studio.errors._internal import ViewDeletionCapacityError

_MAX_DELETION_THREADS = 8
_DELETION_SLOTS = threading.BoundedSemaphore(_MAX_DELETION_THREADS)


@dataclass(frozen=True)
class ViewDeletionResult:
    """The committed workspace and optional retained cleanup tree."""

    workspace: StudioWorkspace
    cleanup: Path | None = None


@dataclass(frozen=True)
class _DeletionClaim:
    worker: asyncio.Future[StudioWorkspace | None]
    claimed: asyncio.Event
    proceed: threading.Event
    abort: threading.Event


def _start_deletion_claim(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
) -> _DeletionClaim:
    loop = asyncio.get_running_loop()
    slots = _DELETION_SLOTS
    if not slots.acquire(blocking=False):
        raise ViewDeletionCapacityError()
    try:
        worker: asyncio.Future[StudioWorkspace | None] = loop.create_future()
        claimed = asyncio.Event()
        proceed = threading.Event()
        abort = threading.Event()

        def remove() -> StudioWorkspace | None:
            with workspace_catalog_lock(studio.view_root):
                current = validate_view_deletion_owner(
                    studio,
                    name,
                    expected_catalog_generation=expected_catalog_generation,
                    expected_generation=expected_generation,
                )
                loop.call_soon_threadsafe(claimed.set)
                proceed.wait()
                if abort.is_set():
                    return None
                with presentation.deleting_view(name):
                    return delete_view(
                        current,
                        name,
                        expected_catalog_generation=expected_catalog_generation,
                        expected_generation=expected_generation,
                    )

        def complete() -> None:
            result: StudioWorkspace | None = None
            failure: BaseException | None = None
            try:
                result = remove()
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
            name=f"marimo-studio-delete-{name}",
            daemon=True,
        )
        thread.start()
    except BaseException:
        slots.release()
        raise
    return _DeletionClaim(worker, claimed, proceed, abort)


async def _wait_for_claim(claim: _DeletionClaim) -> None:
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
            raise RuntimeError("View deletion finished before its owner was claimed")
        return
    await claimed


async def _drain_claim(claim: _DeletionClaim) -> None:
    claim.abort.set()
    claim.proceed.set()
    await settle_ownership_outcome(claim.worker)


async def _coordinate_deletion(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> ViewDeletionResult:
    claim = _start_deletion_claim(
        studio,
        name,
        expected_catalog_generation=expected_catalog_generation,
        expected_generation=expected_generation,
        presentation=presentation,
    )
    entered_development = False
    try:
        await _wait_for_claim(claim)
        async with development.deleting_view(name):
            entered_development = True
            claim.proceed.set()
            try:
                updated = await claim.worker
            except ViewDeletionError as error:
                if error.cleanup is None or not isinstance(
                    error.committed_workspace,
                    StudioWorkspace,
                ):
                    raise
                return ViewDeletionResult(
                    error.committed_workspace,
                    cleanup=error.cleanup,
                )
            if updated is None:
                raise RuntimeError("View deletion owner was released before commit")
            return ViewDeletionResult(updated)
    finally:
        if not entered_development:
            await _drain_claim(claim)


async def delete_owned_view(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> ViewDeletionResult:
    """Delete one observed view after draining every server-side owner."""
    result, failure, cancellation = await settle_ownership_outcome(
        _coordinate_deletion(
            studio,
            name,
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
        raise RuntimeError("View deletion did not produce a terminal result")
    return result
