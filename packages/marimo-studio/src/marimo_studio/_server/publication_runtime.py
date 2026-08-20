"""Adapt notebook publications to runtime-neutral projection capabilities."""

from __future__ import annotations

from marimo_studio._capabilities import (
    PreparedRuntimeState,
    RuntimeAuthority,
    ServerContext,
)
from marimo_studio._server.prepared_views import (
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation import PresentationSnapshot
from marimo_studio._urls import (
    STUDIO_CLIENT_QUERY_PARAM,
    SUPPORT_PATH,
    public_url,
    with_query,
)
from marimo_studio.errors import PublicationUnavailableError


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
    ) -> PreparedRuntimeState:
        if binding_id is None:
            raise PublicationUnavailableError(
                "The zero-Python publication for this view is unavailable. "
                "Open the view in Studio to prepare its current notebook state."
            )
        if authority == "edit":
            if session_id is None or context.internal_url is None:
                raise PublicationUnavailableError(
                    "Studio cannot prepare the zero-Python publication until its "
                    "editor session and local server endpoint are available."
                )
            selection = await self._publications.prepare(
                PreparedViewRequest(
                    snapshot=snapshot,
                    server=context.internal_url,
                    server_token=context.server_token,
                    session_id=session_id,
                    binding_id=binding_id,
                )
            )
        else:
            selection = self._publications.current(
                snapshot.view_name,
                binding_id,
                snapshot.revision,
            )
            if selection is None:
                raise PublicationUnavailableError(
                    "The zero-Python publication for this view and browser is "
                    "unavailable. "
                    "Open the view in Studio to prepare its current notebook state."
                )
        return PreparedRuntimeState(
            instance=selection.instance,
            data={
                "manifestUrl": _manifest_url(
                    context,
                    snapshot.view_name,
                    binding_id,
                    snapshot.revision,
                ),
                "planDigest": selection.plan_digest,
            },
        )


def publication_runtime_projector(
    publications: PreparedViewRegistry,
) -> PublicationRuntimeProjector:
    return PublicationRuntimeProjector(publications)


def _manifest_url(
    context: ServerContext,
    view_name: str,
    binding_id: str,
    revision: str,
) -> str:
    return with_query(
        public_url(
            context.base_url,
            f"{SUPPORT_PATH}/views/{view_name}/zero-python/current",
        ),
        (
            *context.routing_query,
            (STUDIO_CLIENT_QUERY_PARAM, binding_id),
            ("revision", revision),
        ),
    )


__all__ = ["PublicationRuntimeProjector", "publication_runtime_projector"]
