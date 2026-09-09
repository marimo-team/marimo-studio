from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from marimo_export import ExportRepository, StateSpace, open_export
from marimo_export._remote.managed import ManagedServer
from marimo_export.errors import (
    CaptureLimitError,
    CompatibilityError,
    MarimoExportError,
    OutputError,
    SessionError,
    SpecError,
)
from marimo_export.repository import RepositoryLimitError
from marimo_export.sessions import Client

from marimo_studio._prepared.state_space import load_state_space_source
from marimo_studio._server.prepared_views import (
    Connector,
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio.errors import PublicationError

from ..delivery.export_test_support import configure_export_view
from ..helpers import replace_app_shell


def _prepare_failure(
    notebook: Path, error: MarimoExportError, *, single_projection: bool = False
) -> PublicationError:
    view_root = configure_export_view(notebook)
    if single_projection:
        document = view_root / "index.html"
        document.write_text(
            replace_app_shell(
                document.read_text(encoding="utf-8"),
                '<output mo-value="doubled"></output>',
            ),
            encoding="utf-8",
        )

    def plan(**_kwargs: object) -> None:
        raise error

    @contextmanager
    def connector(*_args: object, **_kwargs: object) -> Iterator[Client]:
        yield cast(
            Client, SimpleNamespace(session=lambda _id: SimpleNamespace(plan=plan))
        )

    request = PreparedViewRequest(
        snapshot=NotebookPresentation(notebook).snapshot("dashboard"),
        state_space_source=load_state_space_source(view_root),
        server="http://localhost:2718",
        server_token="test",
        session_id="s_editor",
        binding_id="editor",
    )
    registry = PreparedViewRegistry(notebook, connector=cast(Connector, connector))

    async def prepare() -> PublicationError:
        try:
            with pytest.raises(PublicationError) as raised:
                await registry.prepare(request)
            return raised.value
        finally:
            await registry.close()

    return asyncio.run(prepare())


def test_live_preparation_reports_source_candidates_when_planning_rejects_callbacks(
    notebook_path: Path,
) -> None:
    error = OutputError(
        "Rendered output requires Python functions.",
        code="output_not_portable",
        details={"functions": ["download_as"]},
    )

    failure = _prepare_failure(notebook_path, error)

    assert failure.code == "zero-python-projection-functions"
    details = failure.diagnostic_details()
    assert details["marimo_export"] == {
        "code": "output_not_portable",
        "message": "Rendered output requires Python functions.",
        "details": {"functions": ["download_as"]},
    }
    candidates = details["projections"]
    assert isinstance(candidates, list)
    assert {(item["projection"], item["target"]) for item in candidates} == {
        ("cell", "cell-2"),
        ("value", "doubled"),
        ("output", "doubled"),
    }
    for candidate in candidates:
        assert len(candidate["sources"]) == 1
        assert candidate["sources"][0]["path"] == "index.html"
        assert candidate["sources"][0]["line"] > 0
    assert "Python runtime or Browser runtime" in failure.public_hint
    assert "serializable data" in failure.public_hint


@pytest.mark.parametrize(
    ("error_type", "hint"),
    [
        (SessionError, "notebook is open"),
        (CompatibilityError, "installed Marimo and marimo-export versions"),
        (SpecError, "view projections and configured notebook states"),
        (MarimoExportError, "reported notebook output and state"),
    ],
)
def test_live_preparation_preserves_export_failure_context(
    notebook_path: Path,
    error_type: type[MarimoExportError],
    hint: str,
) -> None:
    error = error_type(
        "Notebook state could not be inspected.",
        code="state_inspection_failed",
        details={"state": "baseline", "reason": "missing input"},
    )

    failure = _prepare_failure(notebook_path, error, single_projection=True)

    assert failure.code == "state_inspection_failed"
    assert "Notebook state could not be inspected." in str(failure)
    assert failure.diagnostic_details() == {
        "runtime": "zero-python",
        "marimo_export": {
            "code": "state_inspection_failed",
            "message": "Notebook state could not be inspected.",
            "details": {"state": "baseline", "reason": "missing input"},
        },
    }
    assert hint in failure.public_hint


@pytest.mark.parametrize(
    ("error_type", "code"),
    [
        (CaptureLimitError, "capture_limit_exceeded"),
        (RepositoryLimitError, "repository_limit_exceeded"),
    ],
)
def test_live_preparation_preserves_resource_limit_context(
    notebook_path: Path,
    error_type: type[MarimoExportError],
    code: str,
) -> None:
    error = error_type(
        "Prepared data exceeds the byte limit.",
        details={"bytes": 2048, "limit": 1024},
    )

    failure = _prepare_failure(notebook_path, error)

    assert failure.status_code == 413
    assert failure.code == "zero-python-state-limit"
    assert failure.diagnostic_details() == {
        "runtime": "zero-python",
        "marimo_export": {
            "code": code,
            "message": "Prepared data exceeds the byte limit.",
            "details": {"bytes": 2048, "limit": 1024},
        },
    }
    assert "Reduce the number of prepared states" in failure.public_hint
    assert "projected outputs" in failure.public_hint


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

            registry = PreparedViewRegistry(notebook, repository=repository)
            request = PreparedViewRequest(
                snapshot=snapshot,
                state_space_source=source,
                server=managed.base_url,
                server_token="test",
                access_token=managed.access_token,
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
