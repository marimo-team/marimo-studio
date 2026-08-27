from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marimo_studio._workspace.models import StudioWorkspace

from .app_helpers import configured, edit_mode, marimo_app, session_manager


@dataclass(frozen=True)
class AgentEditServer:
    studio: StudioWorkspace
    app: Any
    headers: dict[str, str]


def agent_edit_server(
    notebook: Path,
    *,
    token: str = "",
    session_id: str | None = None,
) -> AgentEditServer:
    studio = configured(notebook)
    app = marimo_app(
        studio.notebook,
        token=token,
        skew_protection=bool(token),
    )
    edit_mode(app)
    headers = {"Marimo-Server-Token": str(session_manager(app).skew_protection_token)}
    if session_id is not None:
        headers["Marimo-Session-Id"] = session_id
    return AgentEditServer(studio=studio, app=app, headers=headers)


__all__ = ["AgentEditServer", "agent_edit_server"]
