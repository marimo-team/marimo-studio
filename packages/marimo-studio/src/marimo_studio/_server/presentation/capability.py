"""Authorize one presentation session at one published revision."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from marimo_studio._delivery.urls import SUPPORT_PATH, authored_file_key, public_url
from marimo_studio._server.presentation.isolation import PRESENTATION_SANDBOX
from marimo_studio._server.records import ServerContext

PRESENTATION_PATH = f"{SUPPORT_PATH}/presentation"
PRESENTATION_RESPONSE_HEADERS = {
    "Access-Control-Allow-Origin": "null",
    "Access-Control-Expose-Headers": (
        "ETag, Marimo-Studio-Error, Marimo-Studio-Hint, "
        "Marimo-Studio-Revision, Marimo-Studio-Support-Url, Retry-After"
    ),
    "Content-Security-Policy": f"sandbox {PRESENTATION_SANDBOX}",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Referrer-Policy": "no-referrer",
    "Vary": "Origin",
}

CapabilityKind = Literal["renewal", "revision"]


class _ArtifactIdentity(Protocol):
    @property
    def artifact_revision(self) -> str: ...


class PresentationIdentity(Protocol):
    @property
    def view_name(self) -> str: ...

    @property
    def revision(self) -> str: ...

    @property
    def artifact(self) -> _ArtifactIdentity: ...


_VIEW_PATTERN = r"[a-z][a-z0-9-]*"
_SESSION_PATTERN = r"s_[a-z0-9]{6}"
_REVISION_PATTERN = r"[0-9a-f]{64}"
_FILE_PATTERN = r"[A-Za-z0-9_-]{1,1024}"
_RENEWAL_TOKEN_PATTERN = re.compile(
    rf"d\.(?P<file>{_FILE_PATTERN})\."
    rf"(?P<view>{_VIEW_PATTERN})\."
    rf"(?P<session>{_SESSION_PATTERN})\."
    rf"(?P<runtime>{_SESSION_PATTERN})\."
    r"(?P<signature>[0-9a-f]{64})"
)
_REVISION_TOKEN_PATTERN = re.compile(
    rf"r\.(?P<file>{_FILE_PATTERN})\."
    rf"(?P<view>{_VIEW_PATTERN})\."
    rf"(?P<session>{_SESSION_PATTERN})\."
    rf"(?P<runtime>{_SESSION_PATTERN}|p)\."
    rf"(?P<revision>{_REVISION_PATTERN})\."
    rf"(?P<artifact>{_REVISION_PATTERN})\."
    r"(?P<signature>[0-9a-f]{64})"
)
_DOCUMENT_PATTERN = re.compile(rf"/(?P<view>{_VIEW_PATTERN})/(?:index\.html)?")
_ARTIFACT_PATTERN = re.compile(
    rf"/(?P<view>{_VIEW_PATTERN}){re.escape(SUPPORT_PATH)}/artifacts/"
    rf"(?P<artifact>{_REVISION_PATTERN})/.+"
)
_VIEW_SUPPORT_PATTERN = re.compile(
    rf"{re.escape(SUPPORT_PATH)}/views/(?P<view>{_VIEW_PATTERN})/"
    r"(?P<route>config|values|outputs|dev/events)"
)
_RUNTIME_ASSET_PATTERN = re.compile(rf"{re.escape(SUPPORT_PATH)}/assets/.+")
_NATIVE_READ_PATTERN = re.compile(r"/(?:@file/.+|public/.+|public-files-sw\.js)")

_NATIVE_POST_ROUTES = frozenset(
    {
        "/api/kernel/function_call",
        "/api/kernel/instantiate",
        "/api/kernel/set_model_value",
        "/api/kernel/set_ui_element_value",
        "/api/kernel/stdin",
    }
)


@dataclass(frozen=True)
class PresentationCapability:
    """One server-signed presentation audience."""

    kind: CapabilityKind
    token: str
    file_key: str
    view: str
    session_id: str
    runtime_session_id: str | None = None
    revision: str | None = None
    artifact_revision: str | None = None


@dataclass(frozen=True)
class PresentationCapabilityRoute:
    """A signed presentation namespace and its normalized target route."""

    capability: PresentationCapability
    target: str

    @property
    def token(self) -> str:
        return self.capability.token

    @property
    def file_key(self) -> str:
        return self.capability.file_key

    @property
    def view(self) -> str:
        return self.capability.view

    @property
    def session_id(self) -> str:
        return self.capability.session_id


def presentation_renewal_capability(
    context: ServerContext,
    view_name: str,
    session_id: str,
    runtime_session_id: str,
) -> str:
    """Mint document authority for one server-assigned runtime session."""
    file_token = _file_token(context.file_key)
    unsigned = f"d.{file_token}.{view_name}.{session_id}.{runtime_session_id}"
    signature = _signature(
        context,
        "renewal",
        view_name,
        session_id,
        runtime_session_id,
    )
    return f"{unsigned}.{signature}"


def presentation_revision_capability(
    context: ServerContext,
    snapshot: PresentationIdentity,
    session_id: str,
    runtime_session_id: str | None = None,
) -> str:
    """Mint runtime authority for one exact presentation and artifact revision."""
    artifact_revision = snapshot.artifact.artifact_revision.removeprefix("sha256:")
    runtime_session = runtime_session_id or "p"
    unsigned = (
        f"r.{_file_token(context.file_key)}.{snapshot.view_name}.{session_id}."
        f"{runtime_session}.{snapshot.revision}.{artifact_revision}"
    )
    signature = _signature(
        context,
        "revision",
        snapshot.view_name,
        session_id,
        runtime_session,
        snapshot.revision,
        artifact_revision,
    )
    return f"{unsigned}.{signature}"


def presentation_renewal_url(
    context: ServerContext,
    view_name: str,
    session_id: str,
    runtime_session_id: str,
    target: str = "/",
) -> str:
    """Return the document-only URL for one presentation session."""
    return _capability_url(
        context,
        presentation_renewal_capability(
            context,
            view_name,
            session_id,
            runtime_session_id,
        ),
        target,
    )


def presentation_revision_url(
    context: ServerContext,
    snapshot: PresentationIdentity,
    session_id: str,
    target: str = "/",
    *,
    runtime_session_id: str | None = None,
) -> str:
    """Return the revision-bound URL for one presentation runtime."""
    return _capability_url(
        context,
        presentation_revision_capability(
            context,
            snapshot,
            session_id,
            runtime_session_id,
        ),
        target,
    )


def parse_presentation_capability(token: str) -> PresentationCapability | None:
    """Parse one token without trusting its signature."""
    renewal = _RENEWAL_TOKEN_PATTERN.fullmatch(token)
    if renewal is not None:
        return _parsed_capability("renewal", token, renewal)
    revision = _REVISION_TOKEN_PATTERN.fullmatch(token)
    if revision is not None:
        return _parsed_capability("revision", token, revision)
    return None


def parse_presentation_capability_route(
    relative: str,
) -> PresentationCapabilityRoute | None:
    """Parse one capability path without deciding whether its target is allowed."""
    prefix = f"{PRESENTATION_PATH}/"
    if not relative.startswith(prefix):
        return None
    token, separator, remainder = relative.removeprefix(prefix).partition("/")
    capability = parse_presentation_capability(token)
    if not separator or capability is None:
        return None
    return PresentationCapabilityRoute(capability=capability, target=f"/{remainder}")


def capability_matches(
    capability: PresentationCapability,
    context: ServerContext,
) -> bool:
    """Validate a capability against the resolved notebook process."""
    if capability.file_key != context.file_key:
        return False
    expected = (
        presentation_renewal_capability(
            context,
            capability.view,
            capability.session_id,
            capability.runtime_session_id,
        )
        if capability.kind == "renewal" and capability.runtime_session_id is not None
        else _revision_token(context, capability)
    )
    return expected is not None and hmac.compare_digest(capability.token, expected)


def capability_matches_snapshot(
    capability: PresentationCapability,
    snapshot: PresentationIdentity,
) -> bool:
    """Reject a revision capability after its publication is superseded."""
    if capability.kind != "revision":
        return True
    return (
        capability.view == snapshot.view_name
        and capability.revision == snapshot.revision
        and capability.artifact_revision
        == snapshot.artifact.artifact_revision.removeprefix("sha256:")
    )


def capability_target_matches(route: PresentationCapabilityRoute) -> bool:
    """Require every route to stay inside the signed view and artifact audience."""
    document = _DOCUMENT_PATTERN.fullmatch(route.target)
    if document is not None:
        return (
            route.capability.kind == "renewal" or document.group("view") == route.view
        )
    artifact = _ARTIFACT_PATTERN.fullmatch(route.target)
    if artifact is not None:
        return (
            artifact.group("view") == route.view
            and route.capability.kind == "revision"
            and artifact.group("artifact") == route.capability.artifact_revision
        )
    support = _VIEW_SUPPORT_PATTERN.fullmatch(route.target)
    return (
        support is None
        or support.group("view") == route.view
        or (route.capability.kind == "renewal" and support.group("route") == "config")
    )


def presentation_target_allowed(
    route: PresentationCapabilityRoute,
    method: str,
    scope_type: str,
) -> bool:
    """Return whether this capability kind grants the requested operation."""
    if route.capability.kind == "renewal":
        return (
            scope_type == "http"
            and method in {"GET", "HEAD"}
            and (
                _DOCUMENT_PATTERN.fullmatch(route.target) is not None
                or (
                    (match := _VIEW_SUPPORT_PATTERN.fullmatch(route.target)) is not None
                    and match.group("route") == "config"
                )
            )
        )
    if scope_type == "websocket":
        return route.target == "/ws"
    if scope_type != "http":
        return False
    if method in {"GET", "HEAD"}:
        return bool(
            route.target in {"/health", "/sse", f"{SUPPORT_PATH}/dev/events"}
            or _ARTIFACT_PATTERN.fullmatch(route.target)
            or _RUNTIME_ASSET_PATTERN.fullmatch(route.target)
            or _NATIVE_READ_PATTERN.fullmatch(route.target)
            or (
                (match := _VIEW_SUPPORT_PATTERN.fullmatch(route.target)) is not None
                and match.group("route") in {"config", "dev/events"}
            )
        )
    if method == "POST":
        match = _VIEW_SUPPORT_PATTERN.fullmatch(route.target)
        return route.target in _NATIVE_POST_ROUTES or (
            match is not None and match.group("route") in {"values", "outputs"}
        )
    return False


def presentation_target_session_header(target: str, method: str) -> str | None:
    """Return the session header required by a session-bearing target."""
    if method == "GET" and target.endswith("/config"):
        return "Marimo-Studio-Preview-Session-Id"
    if method == "POST" and (
        target in _NATIVE_POST_ROUTES
        or (
            (match := _VIEW_SUPPORT_PATTERN.fullmatch(target)) is not None
            and match.group("route") in {"values", "outputs"}
        )
    ):
        return "Marimo-Session-Id"
    return None


def capability_view(target: str) -> str | None:
    """Return the view named by a presentation document target."""
    match = _DOCUMENT_PATTERN.fullmatch(target)
    return match.group("view") if match is not None else None


def capability_artifact_target(target: str) -> str | None:
    """Return a normal artifact route for one authorized capability target."""
    return target if _ARTIFACT_PATTERN.fullmatch(target) is not None else None


def capability_support_target(target: str) -> str | None:
    """Return a normal support route for one authorized capability target."""
    return target if target.startswith(SUPPORT_PATH) else None


def _parsed_capability(
    kind: CapabilityKind,
    token: str,
    match: re.Match[str],
) -> PresentationCapability | None:
    file_key = authored_file_key(match.group("file"))
    if file_key is None:
        return None
    return PresentationCapability(
        kind=kind,
        token=token,
        file_key=file_key,
        view=match.group("view"),
        session_id=match.group("session"),
        runtime_session_id=(
            None
            if match.groupdict().get("runtime") in {None, "p"}
            else match.group("runtime")
        ),
        revision=match.groupdict().get("revision"),
        artifact_revision=match.groupdict().get("artifact"),
    )


def _file_token(file_key: str) -> str:
    return base64.urlsafe_b64encode(file_key.encode()).decode().rstrip("=")


def _signature(
    context: ServerContext,
    kind: CapabilityKind,
    view_name: str,
    session_id: str,
    runtime_session_id: str = "",
    revision: str = "",
    artifact_revision: str = "",
) -> str:
    message = "\0".join(
        (
            "marimo-studio-presentation-v1",
            kind,
            context.file_key,
            context.mode,
            context.base_url,
            view_name,
            session_id,
            runtime_session_id,
            revision,
            artifact_revision,
        )
    ).encode()
    return hmac.new(
        context.server_token.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def _revision_token(
    context: ServerContext,
    capability: PresentationCapability,
) -> str | None:
    if capability.revision is None or capability.artifact_revision is None:
        return None
    unsigned = (
        f"r.{_file_token(context.file_key)}.{capability.view}."
        f"{capability.session_id}.{capability.runtime_session_id or 'p'}."
        f"{capability.revision}."
        f"{capability.artifact_revision}"
    )
    signature = _signature(
        context,
        "revision",
        capability.view,
        capability.session_id,
        capability.runtime_session_id or "p",
        capability.revision,
        capability.artifact_revision,
    )
    return f"{unsigned}.{signature}"


def _capability_url(context: ServerContext, token: str, target: str) -> str:
    suffix = target if target.startswith("/") else f"/{target}"
    return public_url(context.base_url, f"{PRESENTATION_PATH}/{token}{suffix}")
