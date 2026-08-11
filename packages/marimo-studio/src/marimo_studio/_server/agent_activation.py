"""Coordinate acknowledged view activation in one Studio browser."""

from __future__ import annotations

import asyncio

from marimo_studio._server.agent_events import ViewActivation
from marimo_studio._server.agent_store import AgentOperationStore
from marimo_studio._server.live_clients import PeerStatus, PeerTarget
from marimo_studio.errors import AgentRequestError


class ActivationCoordinator:
    def __init__(self, store: AgentOperationStore) -> None:
        self._store = store

    async def reserve_generation(self) -> int:
        async with self._store.condition:
            return self._store.next_generation()

    async def activate(self, target: PeerTarget, view: str) -> ViewActivation:
        if not self._store.clients.matches(target, require_connected=True):
            raise AgentRequestError(
                "browser-client-unavailable",
                "The Studio browser disconnected before view activation.",
                status_code=409,
            )
        if target.session_id is None:
            raise AgentRequestError(
                "browser-session-changed",
                "The Studio browser has no active Marimo session.",
                status_code=409,
            )
        async with self._store.condition:
            if self._store.has_operation(target.client_id):
                raise AgentRequestError(
                    "browser-operation-in-progress",
                    "This Studio browser is already handling an agent request.",
                    status_code=409,
                )
            activation = ViewActivation(
                generation=self._store.next_generation(),
                binding_generation=target.binding_generation,
                active_view_generation=target.active_view_generation,
                client_id=target.client_id,
                session_id=target.session_id,
                view=view,
            )
            self._store.activations[target.client_id] = activation
            self._store.condition.notify_all()
        if not self._matches(activation, require_connected=True):
            async with self._store.condition:
                self._store.activations.pop(target.client_id, None)
                self._store.condition.notify_all()
            raise AgentRequestError(
                "browser-session-changed",
                "The Studio browser changed Marimo sessions before activation began.",
                status_code=409,
            )
        return activation

    async def acknowledge(
        self,
        client_id: str,
        generation: int,
        view: str,
    ) -> bool:
        async with self._store.condition:
            activation = self._store.activations.get(client_id)
            acknowledged = self._store.acknowledged_generations.get(client_id)
        if activation is None and acknowledged == generation:
            target = await self._store.clients.target_for_client(client_id)
            return target is not None and target.active_view == view
        if (
            activation is None
            or activation.generation != generation
            or activation.view != view
        ):
            return False
        target = self._target(activation)
        if not await self._store.clients.commit_active_view(target, view):
            return False
        async with self._store.condition:
            if self._store.activations.get(client_id) != activation:
                return False
            self._store.acknowledged_generations[client_id] = generation
            self._store.condition.notify_all()
        return True

    async def wait(self, activation: ViewActivation, timeout: float) -> None:
        timed_out = False
        async with self._store.condition:
            try:
                await asyncio.wait_for(
                    self._store.condition.wait_for(lambda: self._finished(activation)),
                    timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
            except asyncio.CancelledError:
                self._clear(activation)
                raise
            self._clear(activation)
        status = self._store.clients.status(self._target(activation))
        if status is PeerStatus.REBOUND:
            raise AgentRequestError(
                "browser-session-changed",
                "The Studio browser changed Marimo sessions during view activation.",
                status_code=409,
            )
        if status is PeerStatus.UNAVAILABLE:
            raise AgentRequestError(
                "browser-client-unavailable",
                "The Studio browser disconnected during view activation.",
                status_code=409,
            )
        if timed_out:
            code = (
                "activation-timeout"
                if self._store.clients.matches(
                    self._target(activation),
                    require_connected=True,
                )
                else "browser-client-unavailable"
            )
            message = (
                "Studio did not confirm the requested active view."
                if code == "activation-timeout"
                else "The Studio browser disconnected during view activation."
            )
            raise AgentRequestError(code, message, status_code=409)
        target = await self._store.clients.target_for_client(activation.client_id)
        if target is None or target.active_view != activation.view:
            raise AgentRequestError(
                "browser-view-changed",
                "The active Studio view changed during view activation.",
                status_code=409,
            )

    def pending_for(
        self,
        client_id: str,
        delivered: int | None,
    ) -> ViewActivation | None:
        activation = self._store.activations.get(client_id)
        if (
            activation is None
            or activation.generation
            == self._store.acknowledged_generations.get(client_id, 0)
            or activation.generation == delivered
            or not self._matches(activation)
        ):
            return None
        return activation

    def _finished(self, activation: ViewActivation) -> bool:
        return (
            self._store.activations.get(activation.client_id) != activation
            or not self._matches(activation)
            or self._store.acknowledged_generations.get(activation.client_id, 0)
            >= activation.generation
        )

    def _clear(self, activation: ViewActivation) -> None:
        if self._store.activations.get(activation.client_id) == activation:
            self._store.activations.pop(activation.client_id, None)
            self._store.condition.notify_all()

    def _matches(
        self,
        activation: ViewActivation,
        *,
        require_connected: bool = False,
    ) -> bool:
        return self._store.clients.activation_matches(
            self._target(activation),
            activation.view,
            require_connected=require_connected,
        )

    @staticmethod
    def _target(activation: ViewActivation) -> PeerTarget:
        return PeerTarget(
            client_id=activation.client_id,
            session_id=activation.session_id,
            binding_generation=activation.binding_generation,
            active_view=None,
            active_view_generation=activation.active_view_generation,
        )


__all__ = ["ActivationCoordinator"]
