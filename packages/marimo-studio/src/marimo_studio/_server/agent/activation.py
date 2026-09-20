"""Coordinate acknowledged view activation in one Studio browser."""

from __future__ import annotations

import asyncio
from enum import Enum

from marimo_studio._browser_client.records import PreviewAutomationTarget
from marimo_studio._server.agent.clients import PeerStatus, PeerTarget
from marimo_studio._server.agent.events import ViewActivation
from marimo_studio._server.agent.store import (
    AcknowledgedActivation,
    ActivationOperation,
    AgentOperationStore,
    PendingActivation,
    RejectedActivation,
    RetainedActivation,
    coordinator_closed_error,
)
from marimo_studio._workspace.ownership import ObservedViewOwner
from marimo_studio.errors import AgentRequestError, MarimoStudioError


class ActivationAckOutcome(str, Enum):
    APPLIED = "applied"
    RETRYABLE = "retryable"
    REJECTED = "rejected"


class ActivationCoordinator:
    def __init__(self, store: AgentOperationStore) -> None:
        self._store = store

    async def activate(
        self,
        target: PeerTarget,
        view: str,
        *,
        owner: ObservedViewOwner | None = None,
    ) -> ViewActivation:
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
            self._store.require_open()
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
                owner=owner,
            )
            operation = PendingActivation(activation)
            self._store.activation_operations[target.client_id] = operation
            self._store.condition.notify_all()
        async with self._store.condition:
            self._store.require_open()
            if not self._matches(activation, require_connected=True):
                if self._store.activation_operations.get(target.client_id) is operation:
                    self._store.activation_operations.pop(target.client_id)
                self._store.condition.notify_all()
                raise AgentRequestError(
                    "browser-session-changed",
                    "The Studio browser changed Marimo sessions before "
                    "activation began.",
                    status_code=409,
                )
        return activation

    async def acknowledge(
        self,
        client_id: str,
        generation: int,
        view: str,
        *,
        owner: ObservedViewOwner | None = None,
        preview: PreviewAutomationTarget,
    ) -> ActivationAckOutcome:
        async with self._store.condition:
            self._store.require_open()
            operation = self._store.activation_operations.get(client_id)
            if isinstance(
                operation,
                (AcknowledgedActivation, RetainedActivation),
            ) and self._request_matches(operation.activation, generation, view, owner):
                target = await self._store.clients.target_for_client(client_id)
                return (
                    ActivationAckOutcome.APPLIED
                    if target is not None
                    and target.session_id == operation.activation.session_id
                    and target.binding_generation
                    == operation.activation.binding_generation
                    and target.active_view == view
                    and target.active_view_generation
                    == operation.active_view_generation
                    else ActivationAckOutcome.REJECTED
                )
            if not isinstance(
                operation, PendingActivation
            ) or not self._request_matches(
                operation.activation, generation, view, owner
            ):
                return ActivationAckOutcome.REJECTED
            activation = operation.activation
            target = self._target(activation)
            committed = await self._store.clients.commit_active_view(target, view)
            if committed is None:
                return (
                    ActivationAckOutcome.RETRYABLE
                    if self._store.clients.status(
                        target,
                        require_connected=True,
                    )
                    is PeerStatus.UNAVAILABLE
                    else ActivationAckOutcome.REJECTED
                )
            if (
                committed.session_id != activation.session_id
                or committed.binding_generation != activation.binding_generation
            ):
                return ActivationAckOutcome.REJECTED
            self._store.activation_operations[client_id] = AcknowledgedActivation(
                activation=activation,
                active_view_generation=committed.active_view_generation,
                preview=preview,
            )
            self._store.condition.notify_all()
            return ActivationAckOutcome.APPLIED

    async def reject(
        self,
        client_id: str,
        generation: int,
        view: str,
        error: MarimoStudioError,
        *,
        owner: ObservedViewOwner | None = None,
    ) -> ActivationAckOutcome:
        async with self._store.condition:
            self._store.require_open()
            operation = self._store.activation_operations.get(client_id)
            if not isinstance(
                operation, PendingActivation
            ) or not self._request_matches(
                operation.activation, generation, view, owner
            ):
                return ActivationAckOutcome.REJECTED
            self._store.activation_operations[client_id] = RejectedActivation(
                operation.activation,
                error,
            )
            self._store.condition.notify_all()
            return ActivationAckOutcome.REJECTED

    async def wait(
        self, activation: ViewActivation, timeout: float
    ) -> PreviewAutomationTarget:
        timed_out = False
        closed = False
        failure: MarimoStudioError | None = None
        async with self._store.condition:
            try:
                await asyncio.wait_for(
                    self._store.condition.wait_for(lambda: self._finished(activation)),
                    timeout,
                )
            except asyncio.TimeoutError:
                timed_out = not self._finished(activation)
            except asyncio.CancelledError:
                self._discard_unacknowledged(activation)
                raise
            closed = self._store.closed
            operation = self._operation_for(activation)
            if isinstance(operation, RejectedActivation):
                failure = operation.error
            if isinstance(operation, AcknowledgedActivation):
                self._store.activation_operations[activation.client_id] = (
                    RetainedActivation(
                        operation.activation,
                        operation.active_view_generation,
                        operation.preview,
                    )
                )
                self._store.condition.notify_all()
            elif not isinstance(operation, RetainedActivation):
                self._discard_unacknowledged(activation)
        if closed:
            raise coordinator_closed_error()
        if failure is not None:
            raise failure
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

        if not isinstance(operation, (AcknowledgedActivation, RetainedActivation)):
            raise AgentRequestError(
                "activation-unacknowledged",
                "The Studio browser did not acknowledge a ready preview.",
                status_code=409,
            )
        return operation.preview

    def pending_for(
        self,
        client_id: str,
        delivered: int | None,
    ) -> ViewActivation | None:
        operation = self._store.activation_operations.get(client_id)
        if not isinstance(operation, PendingActivation):
            return None
        activation = operation.activation
        if activation.generation == delivered or not self._matches(activation):
            return None
        return activation

    def _finished(self, activation: ViewActivation) -> bool:
        operation = self._operation_for(activation)
        return (
            self._store.closed
            or not isinstance(operation, PendingActivation)
            or not self._matches(activation)
        )

    def _discard_unacknowledged(self, activation: ViewActivation) -> None:
        operation = self._operation_for(activation)
        if isinstance(operation, (PendingActivation, RejectedActivation)):
            self._store.activation_operations.pop(activation.client_id)
            self._store.condition.notify_all()

    def _operation_for(
        self,
        activation: ViewActivation,
    ) -> ActivationOperation | None:
        operation = self._store.activation_operations.get(activation.client_id)
        if operation is None or operation.activation != activation:
            return None
        return operation

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

    @staticmethod
    def _request_matches(
        activation: ViewActivation,
        generation: int,
        view: str,
        owner: ObservedViewOwner | None,
    ) -> bool:
        return (
            activation.generation == generation
            and activation.view == view
            and activation.owner == owner
        )
