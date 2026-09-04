from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import marimo

from marimo_studio._composition import (
    own_programmatic_lifespans,
    programmatic_middleware,
)
from marimo_studio._server.route_policy import StudioRoutePolicy
from marimo_studio._server.security import SecurityPolicy
from marimo_studio._views.api import bind_cell, prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace

from .helpers import replace_app_shell


class _BootstrapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._reading = False
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._reading = tag == "script" and dict(attrs).get("id") == (
            "marimo-studio-bootstrap"
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._reading = False

    def handle_data(self, data: str) -> None:
        if self._reading:
            self.parts.append(data)


def studio_bootstrap(document: str) -> dict[str, Any]:
    parser = _BootstrapParser()
    parser.feed(document)
    return json.loads("".join(parser.parts))


def set_shell(studio: StudioWorkspace, view_name: str, content: str) -> None:
    document = studio.views[view_name].root / "index.html"
    document.write_text(
        replace_app_shell(document.read_text(encoding="utf-8"), content),
        encoding="utf-8",
    )


def created_one_view(notebook: Path) -> StudioWorkspace:
    prepare_view(notebook)
    return load_studio(notebook)


def _configured_dashboard(notebook: Path) -> StudioWorkspace:
    studio = created_one_view(notebook)
    bind_cell(studio, "result", 1)
    studio = load_studio(notebook)
    set_shell(
        studio,
        "dashboard",
        '<span mo-value="doubled"></span>'
        '<marimo-output value="doubled"></marimo-output>'
        '<marimo-cell name="result"></marimo-cell>',
    )
    return studio


def published_dashboard(notebook: Path) -> StudioWorkspace:
    studio = _configured_dashboard(notebook)
    with build_view_project_sync(studio.views[studio.default_view]):
        pass
    return load_studio(notebook)


def configured(notebook: Path) -> StudioWorkspace:
    studio = _configured_dashboard(notebook)
    prepare_view(notebook, "executive")
    studio = load_studio(notebook)
    set_shell(
        studio,
        "executive",
        '<span mo-value="x"></span><marimo-output value="x"></marimo-output>',
    )
    for project in studio.views.values():
        with build_view_project_sync(project):
            pass
    return load_studio(notebook)


def marimo_app(
    notebook: Path,
    *,
    path: str = "/",
    token: str = "",
    programmatic: bool = False,
    route_policy: StudioRoutePolicy | None = None,
    security_policy: SecurityPolicy | None = None,
    skew_protection: bool = False,
) -> Any:
    app = (
        marimo.create_asgi_app(
            quiet=True,
            token=token,
            skew_protection=skew_protection,
        )
        .with_app(
            path=path,
            root=str(notebook),
            middleware=(
                [
                    programmatic_middleware(
                        notebook,
                        security_policy,
                        route_policy=route_policy,
                    )
                ]
                if programmatic
                else None
            ),
        )
        .build()
    )
    return own_programmatic_lifespans(app) if programmatic else app


def session_manager(app: Any) -> Any:
    from starlette.routing import Mount

    mounted: Any = next(route.app for route in app.routes if isinstance(route, Mount))
    return mounted.state.session_manager


def edit_mode(app: Any) -> None:
    from marimo._session.model import SessionMode

    session_manager(app).mode = SessionMode.EDIT


__all__ = [
    "configured",
    "created_one_view",
    "edit_mode",
    "marimo_app",
    "published_dashboard",
    "session_manager",
    "set_shell",
]
