"""Retire one served view name across server lifecycles.

Removing or renaming a view retires its name. The server admits the change,
drains the name's development work, and releases its artifact pins before the
workspace commit moves or deletes the view project. Admission and commit run on
dedicated threads so a busy default executor cannot stall them.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._views.remove import delete_view, require_removable
from marimo_studio._views.rename import rename_view, require_rename_target
from marimo_studio._workspace.config import load_studio, validate_view_name
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    view_retirement_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.ownership import PresentViewOwner, require_owned_view
from marimo_studio.errors import ViewDeletionError
from marimo_studio.errors._internal import ViewRetirementCapacityError

_MAX_RETIREMENT_THREADS = 8
_RETIREMENT_SLOTS = threading.BoundedSemaphore(_MAX_RETIREMENT_THREADS)

_T = TypeVar("_T")


@dataclass(frozen=True)
class RetiredView:
    """The committed workspace and optional retained cleanup tree."""

    workspace: StudioWorkspace
    cleanup: Path | None = None


async def _on_retirement_thread(name: str, work: Callable[[], _T]) -> _T:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[_T] = loop.create_future()

    def run() -> None:
        try:
            result = work()
        except BaseException as error:
            loop.call_soon_threadsafe(done.set_exception, error)
        else:
            loop.call_soon_threadsafe(done.set_result, result)

    threading.Thread(
        target=run,
        name=f"marimo-studio-retire-{name}",
        daemon=True,
    ).start()
    return await done


async def _retire(
    studio: StudioWorkspace,
    name: str,
    *,
    owner: PresentViewOwner,
    admit: Callable[[StudioWorkspace], None],
    commit: Callable[[StudioWorkspace], RetiredView],
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    def admitted() -> StudioWorkspace:
        current = load_studio(studio.config_path)
        require_owned_view(current, name, owner)
        admit(current)
        return current

    def admission() -> None:
        with workspace_catalog_lock(studio.view_root):
            admitted()

    def retirement() -> RetiredView:
        with (
            presentation.retiring_view(name) as release_artifacts,
            view_retirement_lock(studio.view_root, name),
        ):
            current = admitted()
            release_artifacts()
            return commit(current)

    slots = _RETIREMENT_SLOTS
    if not slots.acquire(blocking=False):
        raise ViewRetirementCapacityError()
    try:
        await _on_retirement_thread(name, admission)
        async with development.retiring_view(name):
            return await _on_retirement_thread(name, retirement)
    finally:
        slots.release()


async def retire_owned_view(
    studio: StudioWorkspace,
    name: str,
    *,
    owner: PresentViewOwner,
    admit: Callable[[StudioWorkspace], None],
    commit: Callable[[StudioWorkspace], RetiredView],
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    """Commit a change that retires one observed view name.

    ``admit`` rejects a change that cannot commit before the server drains
    anything. A commit failure leaves the name in service. Cancellation waits
    for the retirement to settle.
    """
    retired, cancellation = await settle_ownership(
        _retire(
            studio,
            name,
            owner=owner,
            admit=admit,
            commit=commit,
            presentation=presentation,
            development=development,
        )
    )
    propagate_cancellation(cancellation)
    return retired


async def delete_owned_view(
    studio: StudioWorkspace,
    name: str,
    *,
    owner: PresentViewOwner,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    """Delete one observed view after draining every server-side owner."""

    def delete(current: StudioWorkspace) -> RetiredView:
        try:
            return RetiredView(delete_view(current, name, owner=owner))
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
        owner=owner,
        admit=lambda current: require_removable(current, name),
        commit=delete,
        presentation=presentation,
        development=development,
    )


async def rename_owned_view(
    studio: StudioWorkspace,
    name: str,
    new_name: str,
    *,
    owner: PresentViewOwner,
    presentation: NotebookPresentation,
    development: DevelopmentCoordinator,
) -> RetiredView:
    """Rename one observed view after draining every server-side owner."""
    validate_view_name(new_name)
    return await retire_owned_view(
        studio,
        name,
        owner=owner,
        admit=lambda current: require_rename_target(current, name, new_name),
        commit=lambda current: RetiredView(
            rename_view(current, name, new_name, owner=owner)
        ),
        presentation=presentation,
        development=development,
    )
