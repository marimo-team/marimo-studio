"""Run one active operation and retain the latest queued work per owner."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)

_Result = TypeVar("_Result")


@dataclass(eq=False)
class _Work:
    key: Hashable
    operation: Callable[[], object]
    waiters: set[_Waiter] = field(default_factory=set)
    started: bool = False


@dataclass(eq=False)
class _Waiter:
    owner: Hashable
    work: _Work
    result: asyncio.Future[object]


class LatestWork(Generic[_Result]):
    """Coalesce one key and supersede queued work from the same owner."""

    def __init__(
        self,
        *,
        superseded_error: Callable[[], BaseException],
        closed_error: Callable[[], BaseException],
    ) -> None:
        self._superseded_error = superseded_error
        self._closed_error = closed_error
        self._flights: dict[Hashable, _Work] = {}
        self._pending: OrderedDict[Hashable, _Work] = OrderedDict()
        self._owner_waiters: dict[Hashable, set[_Waiter]] = {}
        self._active: _Work | None = None
        self._runner: asyncio.Task[None] | None = None
        self._closed = False

    async def run(
        self,
        key: Hashable,
        owner: Hashable,
        operation: Callable[[], _Result],
    ) -> _Result:
        if self._closed:
            raise self._closed_error()
        self._supersede(owner, key)
        work = self._flights.get(key)
        if work is None:
            work = _Work(key, cast(Callable[[], object], operation))
            self._flights[key] = work
            self._pending[key] = work
        waiter = _Waiter(owner, work, asyncio.get_running_loop().create_future())
        work.waiters.add(waiter)
        self._owner_waiters.setdefault(owner, set()).add(waiter)
        self._ensure_runner()
        try:
            return cast(_Result, await asyncio.shield(waiter.result))
        finally:
            self._release(waiter, cancel=not waiter.result.done())

    async def close(self) -> None:
        """Reject queued waiters and drain the active operation."""
        if self._closed:
            return
        self._closed = True
        for waiters in tuple(self._owner_waiters.values()):
            for waiter in tuple(waiters):
                if not waiter.result.done():
                    waiter.result.set_exception(self._closed_error())
                self._release(waiter)
        runner = self._runner
        if runner is None:
            return
        _result, cancellation = await settle_ownership(runner)
        propagate_cancellation(cancellation)

    def _supersede(self, owner: Hashable, key: Hashable) -> None:
        for waiter in tuple(self._owner_waiters.get(owner, ())):
            if waiter.work.key == key or waiter.result.done():
                continue
            waiter.result.set_exception(self._superseded_error())
            self._release(waiter)

    def _release(self, waiter: _Waiter, *, cancel: bool = False) -> None:
        work = waiter.work
        if waiter not in work.waiters:
            return
        work.waiters.remove(waiter)
        owned = self._owner_waiters.get(waiter.owner)
        if owned is not None:
            owned.discard(waiter)
            if not owned:
                self._owner_waiters.pop(waiter.owner, None)
        if cancel and not waiter.result.done():
            waiter.result.cancel()
        if not work.started and not work.waiters:
            self._pending.pop(work.key, None)
            self._flights.pop(work.key, None)

    def _ensure_runner(self) -> None:
        if self._runner is None:
            self._runner = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while self._pending:
                _key, work = self._pending.popitem(last=False)
                if not work.waiters:
                    self._flights.pop(work.key, None)
                    continue
                self._active = work
                work.started = True
                result: object | None = None
                failure: BaseException | None = None
                try:
                    result = await asyncio.to_thread(work.operation)
                except BaseException as error:
                    failure = error
                self._flights.pop(work.key, None)
                self._active = None
                for waiter in tuple(work.waiters):
                    if waiter.result.done():
                        continue
                    if failure is not None:
                        waiter.result.set_exception(failure)
                    else:
                        waiter.result.set_result(result)
        finally:
            self._active = None
            self._runner = None
