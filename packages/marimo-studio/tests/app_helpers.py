from __future__ import annotations

from pathlib import Path
from typing import Any

import marimo

from marimo_studio._compat.server.programmatic import programmatic_middleware
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.workspace import bind_cell, ensure_view

from .helpers import replace_app_shell


def set_shell(studio: StudioWorkspace, view_name: str, content: str) -> None:
    template = studio.views[view_name].template
    template.write_text(
        replace_app_shell(template.read_text(encoding="utf-8"), content),
        encoding="utf-8",
    )


def configured(notebook: Path) -> StudioWorkspace:
    ensure_view(notebook)
    studio = load_studio(notebook)
    bind_cell(studio, "result", 1)
    ensure_view(notebook, "executive")
    studio = load_studio(notebook)
    set_shell(
        studio,
        "dashboard",
        '<span mo-value="doubled"></span>'
        '<marimo-output value="doubled"></marimo-output>'
        '<marimo-cell name="result"></marimo-cell>',
    )
    set_shell(
        studio,
        "executive",
        '<span mo-value="x"></span><marimo-output value="x"></marimo-output>',
    )
    return load_studio(notebook)


def marimo_app(
    notebook: Path,
    *,
    path: str = "/",
    token: str = "",
    programmatic: bool = False,
    skew_protection: bool = False,
) -> Any:
    return (
        marimo.create_asgi_app(
            quiet=True,
            token=token,
            skew_protection=skew_protection,
        )
        .with_app(
            path=path,
            root=str(notebook),
            middleware=([programmatic_middleware(notebook)] if programmatic else None),
        )
        .build()
    )


def session_manager(app: Any) -> Any:
    from starlette.routing import Mount

    mounted: Any = next(route.app for route in app.routes if isinstance(route, Mount))
    return mounted.state.session_manager


def edit_mode(app: Any) -> None:
    from marimo._session.model import SessionMode

    session_manager(app).mode = SessionMode.EDIT


__all__ = ["configured", "edit_mode", "marimo_app", "session_manager", "set_shell"]
