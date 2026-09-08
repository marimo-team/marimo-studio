from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from marimo_export import ExportRepository, StateSpace, open_export
from marimo_export._remote.managed import ManagedServer
from marimo_export.sessions import Client

from marimo_studio._prepared.state_space import load_state_space_source
from marimo_studio._server.prepared_views import (
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation.service import NotebookPresentation

from ..delivery.export_test_support import configure_export_view


@pytest.mark.native_process
def test_configured_states_capture_ordinary_and_ui_inputs(tmp_path: Path) -> None:
    notebook = tmp_path / "mixed.py"
    notebook.write_text(
        """import marimo

app = marimo.App()


@app.cell
def controls():
    import marimo as mo
    factor = 10
    scale = mo.ui.slider(1, 2, value=1)
    return factor, scale


@app.cell
def result(factor, scale):
    doubled = factor * scale.value
    doubled
    return doubled,


if __name__ == "__main__":
    app.run()
""",
        encoding="utf-8",
    )
    view_root = configure_export_view(notebook)
    state_space = StateSpace(
        default_state="baseline",
        states={"baseline": {}, "expanded": {"factor": 100, "scale": 2}},
    )
    (view_root / "states.yaml").write_text(
        json.dumps(state_space.to_value()), encoding="utf-8"
    )
    snapshot = NotebookPresentation(notebook).snapshot("dashboard")
    source = load_state_space_source(view_root)
    original = notebook.read_bytes()
    managed = ManagedServer(notebook, timeout=30)
    try:
        managed.activate()
        with (
            Client(managed.base_url, access_token=managed.access_token) as client,
            ExportRepository.open(tmp_path / "repository") as repository,
        ):
            session = client.session(managed.session_id)

            def connector(
                server: str, *, server_token: str | None = None, timeout: float = 30
            ) -> Client:
                return Client(
                    server, access_token=managed.access_token, timeout=timeout
                )

            registry = PreparedViewRegistry(
                notebook, repository=repository, connector=connector
            )
            request = PreparedViewRequest(
                snapshot=snapshot,
                state_space_source=source,
                server=managed.base_url,
                server_token="test",
                session_id=session.id,
                binding_id=session.id,
            )

            async def scenario() -> None:
                try:
                    publication = await registry.prepare(request)
                    assert publication.selected_inputs == {"factor": 10, "scale": 1}
                    asset = await registry.publication_asset(
                        "dashboard", publication.instance, "index.json"
                    )
                    assert asset is not None
                    with asset:
                        exported = open_export(asset.path.parent)
                        assert (
                            exported.state("baseline").output("value:doubled").scalar()
                            == 10
                        )
                        assert (
                            exported.state("expanded").output("value:doubled").scalar()
                            == 200
                        )
                    for path in ("../index.json", "assets/../../secret", "extra.json"):
                        assert (
                            await registry.publication_asset(
                                "dashboard", publication.instance, path
                            )
                            is None
                        )
                    assert session.observe_inputs(
                        plan=publication.prepared.plan
                    ).values == {"factor": 10, "scale": 1}
                finally:
                    await registry.close()

            asyncio.run(scenario())
    finally:
        managed.stop()
    assert notebook.read_bytes() == original
