"""Compile Studio views for the public prepared-publication controller."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from marimo_export import ExportRepository, PreparedExport
from marimo_export.errors import MarimoExportError
from marimo_export.prepared import PreparedAsset
from marimo_export.publication import (
    PreparedPublication,
    PreparedPublicationCandidate,
    PreparedPublicationController,
)
from marimo_export.sessions import Client, connect
from marimo_export.wire import canonical_json_sha256

from marimo_studio._prepared.cleanup import attempt_cleanup
from marimo_studio._prepared.compiler import CompiledExportView
from marimo_studio._prepared.errors import publication_error
from marimo_studio._prepared.resolve import resolve_prepared_view
from marimo_studio._processes.ownership import propagate_cancellation, settle_ownership
from marimo_studio._server.prepared_progress import PreparedProgress
from marimo_studio._server.prepared_view_models import (
    PreparedView,
    PreparedViewMetadata,
    PreparedViewRequest,
)
from marimo_studio._server.runtime.progress import RuntimeProgress, RuntimeProgressSink

_ROUTE_GRACE_SECONDS = 60.0
_PreparedViewKey = tuple[str, str, str]


class Connector(Protocol):
    def __call__(
        self,
        server: str,
        *,
        access_token: str | None = None,
        server_token: str | None = None,
        timeout: float = 30.0,
    ) -> Client: ...


class PreparedViewRegistry:
    """Adapt Studio view keys and capture metadata to prepared publications."""

    def __init__(
        self,
        notebook: Path,
        *,
        repository: ExportRepository | None = None,
        connector: Connector = connect,
        route_grace_seconds: float = _ROUTE_GRACE_SECONDS,
    ) -> None:
        self.notebook = notebook.resolve()
        self._connector = connector
        self._publications: PreparedPublicationController[
            _PreparedViewKey,
            PreparedViewMetadata,
        ] = PreparedPublicationController(
            repository=repository,
            supersession_key=lambda key: key[:2],
            route_key=lambda key: key[0],
            route_grace_seconds=route_grace_seconds,
        )

    @property
    def active(self) -> bool:
        return self._publications.active

    async def prepare(
        self,
        request: PreparedViewRequest,
        *,
        progress: RuntimeProgressSink | None = None,
    ) -> PreparedView:
        prepared = await self._publications.prepare(
            request.key,
            lambda repository, cancelled: self._prepare(
                request,
                repository,
                cancelled,
                progress,
            ),
            admit=_admit_publication,
        )
        return PreparedView(prepared)

    def current(self, view: str, binding_id: str, revision: str) -> PreparedView | None:
        return self._selected((view, binding_id, revision), poll=False)

    def poll_current(
        self,
        view: str,
        binding_id: str,
        revision: str,
    ) -> PreparedView | None:
        return self._selected((view, binding_id, revision), poll=True)

    def _selected(
        self,
        route: _PreparedViewKey,
        *,
        poll: bool,
    ) -> PreparedView | None:
        prepared = (
            self._publications.poll(route, should_refresh=_observations_changed)
            if poll
            else self._publications.current(route)
        )
        if prepared is None:
            return None
        return PreparedView(prepared)

    def release_binding(self, binding_id: str, view: str | None = None) -> None:
        for key in self._publications.keys:
            if key[1] == binding_id and (view is None or key[0] == view):
                self._publications.release(key)

    async def publication_asset(
        self,
        view: str,
        instance: str,
        relative: str,
    ) -> PreparedAsset | None:
        return self._publications.asset(view, instance, relative)

    async def close(self) -> None:
        await self._publications.close()

    def _prepare(
        self,
        request: PreparedViewRequest,
        repository: ExportRepository,
        cancelled: Callable[[], bool],
        progress: RuntimeProgressSink | None,
    ) -> PreparedPublicationCandidate[PreparedViewMetadata]:
        prepared: PreparedExport | None = None
        compiled: CompiledExportView | None = None
        try:
            if progress is not None:
                progress(RuntimeProgress("Inspecting notebook states"))
            with self._connector(
                request.server,
                access_token=request.access_token,
                server_token=request.server_token,
            ) as client:
                session = client.session(request.session_id)
                request.state_space_source.require_current()
                export_progress = (
                    PreparedProgress(progress) if progress is not None else None
                )
                resolved = resolve_prepared_view(
                    request.snapshot,
                    request.state_space_source,
                    session,
                    repository,
                    progress=export_progress,
                )
                compiled = resolved.compiled
                if cancelled():
                    raise asyncio.CancelledError
                prepared = session.capture(
                    spec=resolved.compiled.spec,
                    repository=repository,
                    cancelled=cancelled,
                    progress=export_progress,
                )
                request.state_space_source.require_current()
            metadata = _prepared_view_metadata(
                request,
                prepared,
                resolved.compiled,
                resolved.selected_inputs,
            )
            return PreparedPublicationCandidate(prepared=prepared, metadata=metadata)
        except BaseException as error:
            if prepared is not None:
                attempt_cleanup(error, prepared.close)
            if isinstance(error, MarimoExportError):
                raise publication_error(error, compiled, request.snapshot) from error
            raise


async def _admit_publication(
    candidate: PreparedPublicationCandidate[PreparedViewMetadata],
) -> None:
    _, cancellation = await settle_ownership(
        asyncio.to_thread(candidate.metadata.request.state_space_source.require_current)
    )
    propagate_cancellation(cancellation)


def _observations_changed(
    repository: ExportRepository,
    publication: PreparedPublication[_PreparedViewKey, PreparedViewMetadata],
) -> bool:
    return (
        repository.observation_revision(publication.plan)
        > publication.plan.observation_revision
    )


def _prepared_view_metadata(
    request: PreparedViewRequest,
    prepared: PreparedExport,
    compiled: CompiledExportView,
    selected_inputs: Mapping[str, object] | None,
) -> PreparedViewMetadata:
    projections = {
        "cells": dict(compiled.bindings.cells),
        "outputs": dict(compiled.bindings.outputs),
        "values": dict(compiled.bindings.values),
    }
    digest = canonical_json_sha256(
        {
            "inputs": list(prepared.plan.inputs),
            "state_space": request.state_space_source.digest,
            "projections": projections,
        }
    )
    return PreparedViewMetadata(
        request=request,
        projections=projections,
        selected_inputs=selected_inputs,
        plan_digest=digest,
    )


__all__ = [
    "Connector",
    "PreparedView",
    "PreparedViewRegistry",
    "PreparedViewRequest",
]
