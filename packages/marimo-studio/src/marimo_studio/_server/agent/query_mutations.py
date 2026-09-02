"""Own active and deferred kernel query mutation lifecycles."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from .query_operations import QueryOperationClaim, QueryOperationState
from .session_bindings import SessionBindingLease

QueryBindingKey = tuple[str, str, int]
DeferredQuery = Callable[
    [QueryOperationClaim, Awaitable[object]],
    Coroutine[Any, Any, None],
]


def lease_query_key(lease: SessionBindingLease) -> QueryBindingKey:
    return (lease.client_id, lease.session_id, lease.binding_generation)


def claim_query_key(claim: QueryOperationClaim) -> QueryBindingKey:
    return (claim.client_id, claim.session_id, claim.binding_generation)


class QueryMutations:
    """Track mutation fences and tasks for exact binding incarnations."""

    def __init__(self) -> None:
        self._active: dict[QueryBindingKey, set[tuple[str, int, int]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._tasks_by_binding: dict[QueryBindingKey, set[asyncio.Task[None]]] = {}

    def close(self) -> tuple[asyncio.Task[None], ...]:
        tasks = tuple(self._tasks)
        self._active.clear()
        self._tasks_by_binding.clear()
        return tasks

    def defer(
        self,
        claim: QueryOperationClaim,
        terminal: Awaitable[object],
        finish: DeferredQuery,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(finish(claim, terminal))
        binding_key = claim_query_key(claim)
        self._tasks.add(task)
        self._tasks_by_binding.setdefault(binding_key, set()).add(task)

        def release(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            binding_tasks = self._tasks_by_binding.get(binding_key)
            if binding_tasks is None:
                return
            binding_tasks.discard(completed)
            if not binding_tasks:
                self._tasks_by_binding.pop(binding_key, None)

        task.add_done_callback(release)
        return task

    def acquire(self, claim: QueryOperationClaim) -> None:
        self._active.setdefault(claim_query_key(claim), set()).add(
            QueryOperationState.identity(claim)
        )

    def finish(self, claim: QueryOperationClaim) -> None:
        binding_key = claim_query_key(claim)
        active = self._active.get(binding_key)
        if active is None:
            return
        active.discard(QueryOperationState.identity(claim))
        if not active:
            self._active.pop(binding_key, None)

    def active(self, lease: SessionBindingLease) -> bool:
        return bool(self._active.get(lease_query_key(lease)))

    def release_binding(
        self,
        lease: SessionBindingLease,
    ) -> tuple[asyncio.Task[None], ...]:
        binding_key = lease_query_key(lease)
        self._active.pop(binding_key, None)
        return tuple(self._tasks_by_binding.pop(binding_key, ()))
