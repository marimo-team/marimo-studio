"""Adapt notebook publications to runtime-neutral projection capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from marimo_studio._delivery.urls import (
    STUDIO_CLIENT_QUERY_PARAM,
    SUPPORT_PATH,
    with_query,
)
from marimo_studio._prepared.state_space import load_state_space_source
from marimo_studio._server.prepared_views import (
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation.capability import presentation_revision_path
from marimo_studio._server.presentation.service import PresentationSnapshot
from marimo_studio._server.records import ServerContext
from marimo_studio._server.runtime.progress import RuntimeProgressSink
from marimo_studio.errors import PublicationError, PublicationUnavailableError

RuntimeAuthority = Literal["read", "edit"]


@dataclass(frozen=True)
class PreparedRuntimeState:
    instance: str
    data: dict[str, object]
    paths: dict[str, str]


class PublicationRuntimeProjector:
    """Project prepared publications through one notebook-scoped coordinator."""

    def __init__(self, publications: PreparedViewRegistry) -> None:
        self._publications = publications

    async def project(
        self,
        snapshot: PresentationSnapshot,
        context: ServerContext,
        authority: RuntimeAuthority,
        session_id: str | None,
        binding_id: str | None,
        presentation_session_id: str | None = None,
        *,
        client_id: str | None = None,
        progress: RuntimeProgressSink | None = None,
    ) -> PreparedRuntimeState:
        if binding_id is None or client_id is None:
            # Prepared states belong to one Studio tab's notebook session. A
            # page without that binding cannot gain one by retrying.
            raise PublicationError(
                "The Prepared runtime follows one Studio tab, and this page is "
                "not bound to one.",
                code="zero-python-binding-unavailable",
                hint=(
                    "Open the view in Studio, or request its preview URL while "
                    "Studio shows the notebook."
                ),
            )
        if authority == "edit":
            if session_id is None or context.internal_url is None:
                raise PublicationUnavailableError(
                    "Studio cannot prepare notebook states for the Prepared "
                    "runtime until its editor session and local server endpoint "
                    "are available."
                )
            selection = await self._publications.prepare(
                PreparedViewRequest(
                    snapshot=snapshot,
                    state_space_source=load_state_space_source(
                        snapshot.resolved.views[snapshot.view_name].view.root
                    ),
                    server=context.internal_url,
                    server_token=context.server_token,
                    access_token=context.access_token,
                    session_id=session_id,
                    binding_id=binding_id,
                ),
                progress=progress,
            )
        else:
            selection = self._publications.current(
                snapshot.view_name,
                binding_id,
                snapshot.revision,
            )
            if selection is None:
                raise PublicationUnavailableError(
                    "The Prepared publication for this view and browser is "
                    "unavailable. "
                    "Open the view in Studio to prepare its current notebook state."
                )
        return PreparedRuntimeState(
            instance=selection.instance,
            data={"planDigest": selection.plan_digest},
            paths={
                "manifest": _manifest_path(
                    context,
                    snapshot,
                    client_id,
                    presentation_session_id,
                ),
            },
        )


def publication_runtime_projector(
    publications: PreparedViewRegistry,
) -> PublicationRuntimeProjector:
    return PublicationRuntimeProjector(publications)


def _manifest_path(
    context: ServerContext,
    snapshot: PresentationSnapshot,
    client_id: str,
    presentation_session_id: str | None,
) -> str:
    if presentation_session_id is None:
        raise PublicationUnavailableError(
            "The Prepared presentation session is unavailable."
        )
    return with_query(
        presentation_revision_path(
            context,
            snapshot,
            presentation_session_id,
            f"{SUPPORT_PATH}/views/{snapshot.view_name}/zero-python/current",
        ),
        (
            *context.routing_query,
            (STUDIO_CLIENT_QUERY_PARAM, client_id),
            ("revision", snapshot.revision),
        ),
    )


__all__ = ["PublicationRuntimeProjector", "publication_runtime_projector"]
