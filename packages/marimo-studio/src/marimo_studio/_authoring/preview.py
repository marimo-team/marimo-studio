"""Resolve a directly visitable view URL from its running server."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from marimo_studio._browser_client.transport import StudioServerConnection, request_text
from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.ownership import (
    ObservedViewOwner,
    require_view_owner,
    workspace_view_owner,
)
from marimo_studio.errors import ProtocolError


async def preview_url(
    notebook: Path,
    view: str,
    connection: StudioServerConnection,
    *,
    runtime: str,
    exact: bool = False,
    owner: ObservedViewOwner | None = None,
) -> str:
    """Return a view URL without operating a browser or waiting for rendering."""
    if not isinstance(runtime, str) or not runtime:
        raise ValueError("runtime must be a non-empty string")
    if not isinstance(exact, bool):
        raise ValueError("exact must be a boolean")
    studio = await asyncio.to_thread(load_studio, notebook)
    require_view_owner(studio, view, owner)
    owner = owner or workspace_view_owner(studio, view)
    query = [
        ("runtime", runtime),
        ("exact", "1" if exact else "0"),
        ("catalog_generation", owner.catalog_generation),
        ("view_generation", owner.view_generation or ""),
    ]
    target = await request_text(
        connection,
        f"{SUPPORT_PATH}/views/{quote(view, safe='')}/preview",
        query=tuple(query),
    )
    parts = urlsplit(target)
    if (
        parts.scheme
        or parts.netloc
        or not parts.path.startswith("/")
        or target.startswith("//")
        or any(character.isspace() for character in target)
    ):
        raise ProtocolError("The Studio server returned an invalid preview URL.")
    current = await asyncio.to_thread(load_studio, notebook)
    require_view_owner(current, view, owner)
    return urljoin(connection.server_url, target)
