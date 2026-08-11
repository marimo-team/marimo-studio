"""Coordinate ordered rendered evidence from one Studio browser."""

from __future__ import annotations

import asyncio
import secrets

from marimo_studio._server.agent_events import ObservationRequest
from marimo_studio._server.agent_store import AgentOperationStore
from marimo_studio._server.live_clients import PeerStatus, PeerTarget
from marimo_studio.agent_models import BrowserObservation
from marimo_studio.errors import AgentRequestError


class ObservationCoordinator:
    def __init__(self, store: AgentOperationStore) -> None:
        self._store = store

    async def request(
        self,
        target: PeerTarget,
        view: str,
        runtime: str,
        runtime_instance: str,
        revision: str,
        *,
        active_view_generation: int | None = None,
    ) -> ObservationRequest:
        if not self._target_matches(
            target,
            view,
            active_view_generation,
            require_connected=True,
        ):
            raise AgentRequestError(
                "browser-view-not-active",
                "The Studio browser changed before browser validation began.",
                status_code=409,
            )
        async with self._store.condition:
            if self._store.has_operation(target.client_id):
                raise AgentRequestError(
                    "browser-operation-in-progress",
                    "This Studio browser is already handling an agent request.",
                    status_code=409,
                )
            request = ObservationRequest(
                request_id=secrets.token_urlsafe(18),
                binding_generation=target.binding_generation,
                client_id=target.client_id,
                session_id=target.session_id,
                view=view,
                runtime=runtime,
                runtime_instance=runtime_instance,
                revision=revision,
                active_view_generation=active_view_generation,
            )
            self._store.requests_for(target.client_id)[request.request_id] = request
            self._store.observation_sequences[request.request_id] = -1
            self._store.condition.notify_all()
        if not self._matches(request, require_connected=True):
            async with self._store.condition:
                self._clear(request)
            raise AgentRequestError(
                "browser-session-changed",
                "The Studio browser changed before browser validation began.",
                status_code=409,
            )
        return request

    async def record(self, observation: BrowserObservation) -> bool:
        request_id = observation.request_id
        client_id = observation.client_id
        sequence = observation.sequence
        if request_id is None or client_id is None or sequence is None:
            return False
        async with self._store.condition:
            request = self._store.observation_requests.get(client_id, {}).get(
                request_id
            )
            previous = self._store.observations.get(request_id)
            if (
                request is None
                or not self._matches(request)
                or (previous is not None and previous.state in {"ready", "error"})
                or sequence <= self._store.observation_sequences.get(request_id, -1)
                or observation.view != request.view
                or observation.runtime != request.runtime
                or observation.runtime_instance != request.runtime_instance
                or observation.revision != request.revision
                or observation.session_id != request.session_id
            ):
                return False
            self._store.observation_sequences[request_id] = sequence
            self._store.observations[request_id] = observation
            self._store.condition.notify_all()
            return True

    async def wait(
        self,
        request: ObservationRequest,
        timeout: float,
    ) -> BrowserObservation:
        timed_out = False
        async with self._store.condition:
            try:
                await asyncio.wait_for(
                    self._store.condition.wait_for(lambda: self._finished(request)),
                    timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
            except asyncio.CancelledError:
                self._store.observations.pop(request.request_id, None)
                raise
            finally:
                self._clear(request)
            observed = self._store.observations.pop(request.request_id, None)
        status = self._store.clients.status(self._target(request))
        if status is PeerStatus.REBOUND:
            return self._unobserved(
                request,
                "browser-session-changed",
                "The Studio browser changed Marimo sessions during browser validation.",
            )
        if status is PeerStatus.UNAVAILABLE:
            return self._unobserved(
                request,
                "browser-client-unavailable",
                "The Studio browser disconnected during browser validation.",
            )
        if not self._matches(request):
            return self._unobserved(
                request,
                "browser-view-not-active",
                "The Studio browser changed active views during validation.",
            )
        if observed is not None:
            return observed
        if timed_out:
            if not self._store.clients.matches(
                self._target(request),
                require_connected=True,
            ):
                return self._unobserved(
                    request,
                    "browser-client-unavailable",
                    "The Studio browser disconnected during browser validation.",
                )
            return self._unobserved(
                request,
                "browser-observation-timeout",
                "Studio did not return fresh browser evidence in time.",
            )
        raise RuntimeError("Observation wait completed without a terminal state")

    def pending_for(
        self,
        client_id: str,
        delivered: str | None,
    ) -> tuple[ObservationRequest, ...]:
        return tuple(
            request
            for request_id, request in self._store.observation_requests.get(
                client_id, {}
            ).items()
            if request_id != delivered and self._matches(request)
        )

    def _finished(self, request: ObservationRequest) -> bool:
        observation = self._store.observations.get(request.request_id)
        return (
            request
            not in self._store.observation_requests.get(request.client_id, {}).values()
            or not self._matches(request)
            or (observation is not None and observation.state in {"ready", "error"})
        )

    def _clear(self, request: ObservationRequest) -> None:
        requests = self._store.observation_requests.get(request.client_id)
        if requests is not None:
            requests.pop(request.request_id, None)
            if not requests:
                self._store.observation_requests.pop(request.client_id, None)
        self._store.observation_sequences.pop(request.request_id, None)
        self._store.condition.notify_all()

    def _matches(
        self,
        request: ObservationRequest,
        *,
        require_connected: bool = False,
    ) -> bool:
        return self._target_matches(
            self._target(request),
            request.view,
            request.active_view_generation,
            require_connected=require_connected,
        )

    def _target_matches(
        self,
        target: PeerTarget,
        view: str,
        active_view_generation: int | None,
        *,
        require_connected: bool = False,
    ) -> bool:
        return self._store.clients.matches(
            target,
            require_connected=require_connected,
            active_view=view,
            active_view_generation=active_view_generation,
        )

    @staticmethod
    def _target(request: ObservationRequest) -> PeerTarget:
        return PeerTarget(
            client_id=request.client_id,
            session_id=request.session_id,
            binding_generation=request.binding_generation,
            active_view=request.view,
            active_view_generation=request.active_view_generation or 0,
        )

    @staticmethod
    def _unobserved(
        request: ObservationRequest,
        code: str,
        message: str,
    ) -> BrowserObservation:
        return BrowserObservation(
            view=request.view,
            runtime=request.runtime,
            runtime_instance=request.runtime_instance,
            revision=request.revision,
            state="not-observed",
            code=code,
            message=message,
            client_id=request.client_id,
            request_id=request.request_id,
        )


__all__ = ["ObservationCoordinator"]
