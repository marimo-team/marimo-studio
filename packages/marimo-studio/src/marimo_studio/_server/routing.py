"""Recognize Studio-owned page routes without touching server state."""

from __future__ import annotations

import re
from dataclasses import dataclass

from marimo_studio._delivery.urls import STUDIO_PATH, SUPPORT_PATH, authored_file_key
from marimo_studio._workspace.models import (
    RESERVED_VIEW_ASSET_NAMES,
    RESERVED_VIEW_NAMES,
    VIEW_PATTERN,
    StudioWorkspace,
)


@dataclass(frozen=True)
class AuthoredViewRoute:
    file_key: str
    relative: str


@dataclass(frozen=True)
class ArtifactAssetRoute:
    """One public file from an immutable view artifact revision."""

    view: str
    revision: str
    asset: str


def authored_view_route(relative: str) -> AuthoredViewRoute | None:
    """Resolve a notebook-scoped route used by browser-relative view files."""
    prefix = f"{SUPPORT_PATH}/notebooks/"
    if not relative.startswith(prefix):
        return None
    token, separator, route = relative.removeprefix(prefix).partition("/views/")
    if not separator:
        return None
    file_key = authored_file_key(token)
    if file_key is None:
        return None
    return AuthoredViewRoute(file_key=file_key, relative=f"/{route}")


def native_editor_target(relative: str) -> str | None:
    """Map the explicit native-editor mount back to Marimo's root routes."""
    prefix = f"{SUPPORT_PATH}/editor"
    if relative.rstrip("/") == prefix:
        return "/"
    if relative.startswith(f"{prefix}/"):
        return f"/{relative.removeprefix(f'{prefix}/')}"
    return None


def is_support_route(relative: str) -> bool:
    return relative == SUPPORT_PATH or relative.startswith(f"{SUPPORT_PATH}/")


def could_handle(relative: str, mode: str) -> bool:
    """Return whether a path can belong to Studio in the active mode."""
    if is_support_route(relative):
        return True
    if relative in {"", "/"} and mode in {"edit", "run"}:
        return True
    parts = relative.strip("/").split("/")
    if mode == "edit" and parts[0] == STUDIO_PATH.strip("/"):
        return len(parts) in {1, 2}
    return (
        len(parts) >= 1
        and VIEW_PATTERN.fullmatch(parts[0]) is not None
        and parts[0] not in RESERVED_VIEW_NAMES
    )


def document_view(relative: str, studio: StudioWorkspace, mode: str) -> str | None:
    """Resolve a presentation document path to its view name."""
    if mode == "run" and relative in {"", "/"}:
        return studio.default_view
    parts = relative.strip("/").split("/")
    if len(parts) == 1:
        return parts[0] if parts[0] in studio.views else None
    return None


def view_asset(relative: str, studio: StudioWorkspace) -> ArtifactAssetRoute | None:
    """Resolve an artifact-revision-qualified public file route."""
    parts = relative.strip("/").split("/")
    if (
        len(parts) < 5
        or parts[0] not in studio.views
        or parts[1:3] != [SUPPORT_PATH.strip("/"), "artifacts"]
        or re.fullmatch(r"[0-9a-f]{64}", parts[3]) is None
    ):
        return None
    return ArtifactAssetRoute(
        view=parts[0],
        revision=f"sha256:{parts[3]}",
        asset="/".join(parts[4:]),
    )


def view_route_alias(relative: str, studio: StudioWorkspace) -> str | None:
    """Resolve browser-relative support and Marimo resource URLs."""
    parts = relative.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in studio.views:
        return None
    nested = parts[1].casefold()
    if nested == SUPPORT_PATH.strip("/") and parts[2:3] == ["artifacts"]:
        return None
    if nested in RESERVED_VIEW_ASSET_NAMES:
        return "/" + "/".join((nested, *parts[2:]))
    return None


def studio_view(relative: str, studio: StudioWorkspace, mode: str) -> str | None:
    """Resolve an edit workspace path to its selected view name."""
    if mode != "edit":
        return None
    parts = relative.strip("/").split("/")
    if parts == [STUDIO_PATH.strip("/")]:
        return studio.default_view
    if len(parts) == 2 and parts[0] == STUDIO_PATH.strip("/"):
        return parts[1] if parts[1] in studio.views else None
    return None


def is_studio_landing(relative: str, mode: str) -> bool:
    """Return whether the request should enter the edit workspace."""
    return mode == "edit" and relative in {"", "/"}
