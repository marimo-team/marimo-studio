"""Run workspace lifecycle operations across process boundaries."""

from __future__ import annotations

import time
from pathlib import Path

from marimo_studio._views.api import prepare_view
from marimo_studio._views.remove import delete_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import canonical_view_root
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    workspace_catalog_lock,
)
from marimo_studio.errors import (
    LastViewError,
    ViewExistsError,
)

from ..helpers import replace_app_shell


def _delete_view_in_process(
    notebook: str,
    view_name: str,
    signals: str,
    participants: int,
) -> str:
    signal_root = Path(signals)
    signal_root.joinpath(f"{view_name}.ready").write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 5
    while len(tuple(signal_root.glob("*.ready"))) < participants:
        if time.monotonic() >= deadline:
            raise TimeoutError("Concurrent deletion participants did not start")
        time.sleep(0.01)
    try:
        notebook_path = Path(notebook)
        with workspace_catalog_lock(canonical_view_root(notebook_path)):
            delete_view(load_studio(notebook_path), view_name)
    except LastViewError:
        return "last-view"
    return "deleted"


def _reject_manifestless_view_in_process(notebook: str, view_name: str) -> str:
    try:
        prepare_view(Path(notebook), view_name)
    except ViewExistsError as error:
        return str(error)
    raise AssertionError("Manifestless view directory was adopted")


def _create_view_in_process(
    notebook: str,
    view_name: str,
    signals: str,
    participants: int,
) -> str:
    signal_root = Path(signals)
    signal_root.joinpath(f"{view_name}.ready").write_text("ready\n", encoding="utf-8")
    deadline = time.monotonic() + 5
    while len(tuple(signal_root.glob("*.ready"))) < participants:
        if time.monotonic() >= deadline:
            raise TimeoutError("Concurrent creation participants did not start")
        time.sleep(0.01)
    return prepare_view(Path(notebook), view_name).name


def _shell(studio: StudioWorkspace, view_name: str, content: str) -> None:
    template = studio.views[view_name].root / "index.html"
    template.write_text(
        replace_app_shell(template.read_text(encoding="utf-8"), content),
        encoding="utf-8",
    )
