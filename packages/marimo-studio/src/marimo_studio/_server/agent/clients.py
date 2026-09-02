"""Bind each Studio browser to its intended editor session and active view.

The registry tracks the current browser connection, its Marimo editor session,
the view it is showing, and any view handoff in progress. A short reconnect
window keeps the editor session available through a network interruption while
the replacement browser connection becomes ready.

One native session belongs to one Studio client at a time. Agent work and public
query writes are checked against the browser and editor session they observed.
Retrying the same query does not apply it twice, and an older URL update cannot
overtake a newer one. Closing the registry rejects pending work and releases
every remaining browser-to-session association.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from .query_mutations import QueryMutations
from .query_operations import QueryOperationClaim
from .query_operations import QueryOperationStatus as QueryOperationStatus
from .session_bindings import (
    ClientBinding,
    SessionBindingLease,
    SessionBindings,
)
from .workspace_presence import (
    LiveClient,
    PeerSnapshot,
    PeerStatus,
    PeerTarget,
    WorkspacePresence,
    WorkspaceStreamLease,
)


class StudioClientRegistry:
    """Own Studio browser presence, session identity, and query idempotency."""

    def __init__(
        self,
        *,
        disconnect_grace: float = 10.0,
        terminal_handoff_limit: int = 256,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if terminal_handoff_limit < 1:
            raise ValueError("terminal_handoff_limit must be positive")
        self._condition = asyncio.Condition()
        self._session_clients: dict[str, str] = {}
        self._presence = WorkspacePresence(
            self._session_clients,
            terminal_handoff_limit=terminal_handoff_limit,
        )
        self._clients = self._presence.clients
        self._bindings = SessionBindings(self._clients, self._session_clients)
        self._query_mutations = QueryMutations()
        self._disconnect_grace = disconnect_grace
        self._clock = clock
        self._wait = wait
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._listeners: set[Callable[[], None]] = set()
        self._closed = False

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        if self._closed:
            raise RuntimeError("Studio client registry is closed")
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            tasks = (*self._cleanup_tasks, *self._query_mutations.close())
            self._bindings.close()
            self._presence.clear()
            self._session_clients.clear()
            self._condition.notify_all()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._listeners.clear()

    def defer_query_mutation(
        self,
        claim: QueryOperationClaim,
        terminal: Awaitable[object],
    ) -> asyncio.Task[None] | None:
        if self._closed:
            return None
        return self._query_mutations.defer(
            claim,
            terminal,
            self._finish_deferred_query,
        )

    async def reserve_stream(
        self,
        client_id: str,
        stream_generation: int,
        active_view: str | None = None,
    ) -> WorkspaceStreamLease | None:
        async with self._condition:
            self._require_open_locked()
            lease = self._presence.reserve_stream(
                client_id,
                stream_generation,
                active_view,
            )
            if lease is None:
                return None
            self._condition.notify_all()
        self._publish()
        return lease

    async def promote_stream(self, lease: WorkspaceStreamLease) -> bool:
        async with self._condition:
            if self._closed:
                return False
            if not self._presence.promote_stream(lease):
                return False
            self._condition.notify_all()
        self._publish()
        return True

    async def release_stream(self, lease: WorkspaceStreamLease) -> None:
        async with self._condition:
            client = self._presence.release_stream(lease)
            if client is None:
                return
            if not client.streams:
                self._mark_disconnected(lease.client_id, client)
            self._condition.notify_all()
        self._publish()

    async def connect_stream(
        self,
        client_id: str,
        stream_generation: int,
        active_view: str | None = None,
    ) -> WorkspaceStreamLease | None:
        lease = await self.reserve_stream(
            client_id,
            stream_generation,
            active_view,
        )
        if lease is None:
            return None
        if await self.promote_stream(lease):
            return lease
        await self.release_stream(lease)
        return None

    async def bind_session(
        self,
        session_id: str,
        client_id: str,
        *,
        new_incarnation: bool = False,
    ) -> SessionBindingLease | None:
        publish = False
        async with self._condition:
            self._require_open_locked()
            client = self._presence.client(client_id)
            update = self._bindings.bind(
                session_id,
                client_id,
                client,
                new_incarnation=new_incarnation,
            )
            if update.lease is None:
                return None
            if update.changed:
                client.query_operations.reset()
                self._presence.terminalize_handoff(client)
                self._condition.notify_all()
                publish = True
            self._mark_disconnected(client_id, client)
        if publish:
            self._publish()
        return update.lease

    def reject_session_binding(self, lease: SessionBindingLease) -> bool:
        """Invalidate one rejected connector binding on the registry event loop."""
        if self._closed or not self._bindings.current(lease):
            return False
        if not self._query_mutations.active(lease):
            if not self._reject_session_binding_locked(lease, notify=False):
                return False
            self._publish()
            self._schedule_notify()
            return True
        if lease.rejection_task is not None:
            return True
        task = asyncio.create_task(self._finish_rejected_session_binding(lease))
        lease.rejection_task = task
        self._cleanup_tasks.add(task)
        task.add_done_callback(
            lambda completed: self._clear_rejection_task(lease, completed)
        )
        task.add_done_callback(self._cleanup_tasks.discard)
        return True

    @staticmethod
    def _clear_rejection_task(
        lease: SessionBindingLease,
        task: asyncio.Task[None],
    ) -> None:
        if lease.rejection_task is task:
            lease.rejection_task = None

    async def _finish_rejected_session_binding(
        self,
        lease: SessionBindingLease,
    ) -> None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: (
                    self._closed
                    or not lease.current
                    or not self._query_mutations.active(lease)
                )
            )
            if self._closed or not self._bindings.current(lease):
                return
            changed = self._reject_session_binding_locked(lease, notify=True)
        if changed:
            self._publish()

    def _reject_session_binding_locked(
        self,
        lease: SessionBindingLease,
        *,
        notify: bool,
    ) -> bool:
        client = self._clients.get(lease.client_id)
        if client is None or not self._bindings.reject(lease):
            return False
        client.query_operations.reset()
        if not client.streams:
            self._discard_locked(lease.client_id)
        if notify:
            self._condition.notify_all()
        return True

    def accept_session_binding(
        self,
        lease: SessionBindingLease,
        native_claim: object,
    ) -> SessionBindingLease | None:
        """Commit one native session incarnation to its exact editor binding."""
        client = self._clients.get(lease.client_id)
        if self._closed or client is None:
            return None
        if lease.rejection_task is not None:
            lease.rejection_task.cancel()
            lease.rejection_task = None
        update = self._bindings.accept(lease, native_claim)
        if update.lease is None:
            return None
        if update.replaced:
            client.query_operations.reset()
            self._presence.terminalize_handoff(client)
        if update.changed:
            self._publish()
            self._schedule_notify()
        return update.lease

    def native_session_closed(
        self,
        lease: SessionBindingLease,
    ) -> asyncio.Task[None] | None:
        """Release one exact binding after its native session has closed."""
        if self._closed:
            return None
        task = asyncio.create_task(self._finish_native_session_close(lease))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)
        return task

    async def _notify_waiters(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    def _schedule_notify(self) -> None:
        task = asyncio.create_task(self._notify_waiters())
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _finish_native_session_close(self, lease: SessionBindingLease) -> None:
        released_binding = False
        async with self._condition:
            client = self._clients.get(lease.client_id)
            if self._closed:
                return
            binding_tasks = self._query_mutations.release_binding(lease)
            if client is not None and self._bindings.native_closed(lease):
                client.query_operations.reset()
                if not client.streams:
                    self._discard_locked(lease.client_id)
                released_binding = True
            self._condition.notify_all()
        for task in binding_tasks:
            task.cancel()
        if binding_tasks:
            await asyncio.gather(*binding_tasks, return_exceptions=True)
        if released_binding:
            self._publish()

    async def binding_for_session(self, session_id: str) -> ClientBinding | None:
        async with self._condition:
            return self._bindings.for_session(session_id)

    async def binding_for_client(self, client_id: str) -> ClientBinding | None:
        async with self._condition:
            return self._bindings.for_client(client_id)

    async def session_for_client(self, client_id: str) -> str | None:
        async with self._condition:
            return self._bindings.session_for_client(client_id)

    async def target_for_client(self, client_id: str) -> PeerTarget | None:
        async with self._condition:
            return self._presence.target(client_id)

    async def snapshot_for_client(self, client_id: str) -> PeerSnapshot | None:
        async with self._condition:
            target = self._presence.target(client_id)
            client = self._clients.get(client_id)
            if target is None or client is None:
                return None
            return PeerSnapshot(
                target=target,
                binding_replaced=client.binding_count > 1,
            )

    async def begin_active_view_handoff(
        self,
        client_id: str,
        operation_id: str,
        from_view: str,
        to_view: str,
    ) -> bool:
        async with self._condition:
            self._require_open_locked()
            if not self._presence.begin_handoff(
                client_id,
                operation_id,
                from_view,
                to_view,
            ):
                return False
            self._condition.notify_all()
        self._publish()
        return True

    async def rollback_active_view_handoff(
        self,
        client_id: str,
        operation_id: str,
    ) -> bool:
        changed = False
        async with self._condition:
            result, changed = self._presence.rollback_handoff(client_id, operation_id)
            if changed:
                self._condition.notify_all()
        if changed:
            self._publish()
        return result

    async def snapshot_for_stream(
        self,
        lease: WorkspaceStreamLease,
    ) -> PeerSnapshot | None:
        async with self._condition:
            return self._presence.snapshot_for_stream(lease)

    async def retained_binding_generations(self) -> dict[str, int]:
        """Return the identity generation retained for each browser client."""
        async with self._condition:
            return self._bindings.retained_generations()

    async def claim_query_operation(
        self,
        client_id: str,
        operation_id: str,
        expected_session_id: str,
        fingerprint: str,
        query_generation: int,
    ) -> QueryOperationClaim | None:
        async with self._condition:
            client = self._clients.get(client_id)
            if (
                client is None
                or not self._presence.is_connected(client)
                or client.session_id != expected_session_id
                or self._session_clients.get(expected_session_id) != client_id
            ):
                return None
            return client.query_operations.claim(
                client_id=client_id,
                session_id=expected_session_id,
                binding_generation=client.binding_generation,
                operation_id=operation_id,
                fingerprint=fingerprint,
                query_generation=query_generation,
            )

    async def commit_query_operation(
        self,
        claim: QueryOperationClaim,
    ) -> bool:
        async with self._condition:
            client = self._clients.get(claim.client_id)
            if (
                client is None
                or not self._presence.is_connected(client)
                or client.session_id != claim.session_id
                or client.binding_generation != claim.binding_generation
                or self._session_clients.get(claim.session_id) != claim.client_id
            ):
                self._release_query_operation_locked(claim)
                return False
            return client.query_operations.commit(claim)

    async def acquire_query_mutation(self, claim: QueryOperationClaim) -> bool:
        async with self._condition:
            client = self._clients.get(claim.client_id)
            if (
                client is None
                or not self._presence.is_connected(client)
                or client.session_id != claim.session_id
                or client.binding_generation != claim.binding_generation
                or self._session_clients.get(claim.session_id) != claim.client_id
            ):
                return False
            if not client.query_operations.acquire(claim):
                return False
            self._query_mutations.acquire(claim)
            return True

    async def finish_query_mutation(self, claim: QueryOperationClaim) -> None:
        async with self._condition:
            client = self._clients.get(claim.client_id)
            if client is not None:
                client.query_operations.finish(claim)
            self._query_mutations.finish(claim)
            self._condition.notify_all()

    async def release_query_operation(
        self,
        claim: QueryOperationClaim,
    ) -> None:
        async with self._condition:
            self._release_query_operation_locked(claim)

    async def wait_for_session_target(
        self,
        session_id: str,
        timeout: float,
    ) -> PeerTarget | None:
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(
                        lambda: (
                            self._closed or self._presence.connected_session(session_id)
                        )
                    ),
                    timeout,
                )
            except asyncio.TimeoutError:
                return None
            return self._presence.target(self._session_clients.get(session_id))

    async def select_target(
        self,
        *,
        session_id: str | None = None,
        client_id: str | None = None,
    ) -> PeerTarget:
        async with self._condition:
            return self._presence.select_target(
                session_id=session_id,
                client_id=client_id,
            )

    def matches(
        self,
        target: PeerTarget,
        *,
        require_connected: bool = False,
        active_view: str | None = None,
        active_view_generation: int | None = None,
    ) -> bool:
        return self._presence.matches(
            target,
            require_connected=require_connected,
            active_view=active_view,
            active_view_generation=active_view_generation,
        )

    def status(
        self,
        target: PeerTarget,
        *,
        require_connected: bool = False,
    ) -> PeerStatus:
        return self._presence.status(target, require_connected=require_connected)

    async def commit_active_view(
        self,
        target: PeerTarget,
        view: str,
    ) -> PeerTarget | None:
        async with self._condition:
            committed = self._presence.commit_active_view(target, view)
            if committed is None:
                return None
            self._condition.notify_all()
        self._publish()
        return committed

    def activation_matches(
        self,
        target: PeerTarget,
        view: str,
        *,
        require_connected: bool = False,
    ) -> bool:
        return self._presence.activation_matches(
            target,
            view,
            require_connected=require_connected,
        )

    async def _finish_deferred_query(
        self,
        claim: QueryOperationClaim,
        terminal: Awaitable[object],
    ) -> None:
        committed = False
        try:
            result = await terminal
            if isinstance(result, dict) and result.get("status") in {
                "applied",
                "superseded",
            }:
                committed = await self.commit_query_operation(claim)
        except BaseException:
            pass
        finally:
            if not committed:
                await self.release_query_operation(claim)
            await self.finish_query_mutation(claim)

    def _release_query_operation_locked(self, claim: QueryOperationClaim) -> None:
        client = self._clients.get(claim.client_id)
        if (
            client is not None
            and client.session_id == claim.session_id
            and client.binding_generation == claim.binding_generation
            and self._session_clients.get(claim.session_id) == claim.client_id
        ):
            client.query_operations.release(claim)

    def _schedule_cleanup(self, client_id: str, disconnected_at: float) -> None:
        if self._closed:
            return
        task = asyncio.create_task(
            self._cleanup_disconnected_client(client_id, disconnected_at)
        )
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    def _mark_disconnected(self, client_id: str, client: LiveClient) -> None:
        if client.streams or self._closed:
            return
        client.disconnected_at = self._clock()
        self._schedule_cleanup(client_id, client.disconnected_at)

    async def _cleanup_disconnected_client(
        self,
        client_id: str,
        disconnected_at: float,
    ) -> None:
        await self._wait(self._disconnect_grace)
        async with self._condition:
            client = self._clients.get(client_id)
            if (
                self._closed
                or client is None
                or client.streams
                or client.disconnected_at != disconnected_at
            ):
                return
            if (
                client.binding_lease is not None
                and client.binding_lease.native_claim is not None
            ):
                self._presence.expire_disconnect(client)
            else:
                self._discard_locked(client_id)
            self._condition.notify_all()
        self._publish()

    def _discard_locked(self, client_id: str) -> None:
        self._bindings.discard(client_id)
        self._presence.discard(client_id)

    def _publish(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _require_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("Studio client registry is closed")
