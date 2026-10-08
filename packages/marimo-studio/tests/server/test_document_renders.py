from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace import load_studio
from marimo_studio.view_providers import BuildResult, RenderRequest, Representation
from marimo_studio.view_providers._builtin.typst import provider as typst

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app

pytestmark = pytest.mark.skipif(
    not typst.availability().available,
    reason="marimo-studio[typst] is unavailable",
)

REPORT = """#import "marimo.typ": marimo_output, marimo_value
#let total = marimo_value("doubled", default: 0)
#assert(total < 100, message: "doubled is too large")
Total #total
#marimo_output("chart", width: 4cm)
"""


def _svg(height: int) -> bytes:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="{height}"/>'
    return svg.encode()


def _svg_output(height: int) -> dict[str, str]:
    data = base64.b64encode(_svg(height)).decode("ascii")
    return {"mimetype": "image/svg+xml", "data": f"data:image/svg+xml;base64,{data}"}


@pytest.fixture
def notebook(notebook_path: Path) -> Path:
    _configured(notebook_path)
    prepare_view(notebook_path, "report", starter="marimo-studio/typst:default")
    project = load_studio(notebook_path).views["report"]
    project.root.joinpath("main.typ").write_text(REPORT, encoding="utf-8")
    with build_view_project_sync(project):
        pass
    return notebook_path


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    render = type(typst).render

    def counted(request: RenderRequest) -> BuildResult:
        cells = {f"cell:{name}": media for name, media in request.cells.items()}
        calls.append({**request.values, **request.outputs, **cells})
        return render(typst, request)

    monkeypatch.setattr(typst, "render", counted)
    return calls


def _post(
    client: TestClient,
    view: str,
    values: dict[str, Any],
    outputs: dict[str, dict[str, str]] | None = None,
) -> Any:
    revision = client.get(f"/_marimo-studio/views/{view}/config").json()["revision"]
    return client.post(
        f"/_marimo-studio/views/{view}/render",
        json={
            "revision": revision,
            "values": values,
            "outputs": outputs or {},
            "cells": {},
        },
    )


def test_edit_mode_renders_posted_values_once_per_value_set(
    notebook: Path,
    renders: list[dict[str, Any]],
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        first = _post(client, "report", {"doubled": 42})
        repeated = _post(client, "report", {"doubled": 42.0})
        other = _post(client, "report", {"doubled": 7})

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/pdf"
    assert first.content.startswith(b"%PDF-")
    assert repeated.content == first.content
    assert other.content != first.content
    assert renders == [{"doubled": 42}, {"doubled": 7}]


def test_concurrent_identical_renders_share_one_rendition_per_worker(
    notebook: Path,
    renders: list[dict[str, Any]],
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(
            pool.map(lambda _: _post(client, "report", {"doubled": 42}), range(6))
        )

    assert {response.status_code for response in responses} == {200}
    assert len({response.content for response in responses}) == 1
    # Two render workers can start before either finishes. Every request
    # queued behind them reuses the stored rendition.
    assert 1 <= len(renders) <= 2


CELL_REPORT = """#import "marimo.typ": marimo_cell
#let plot = marimo_cell("plot", width: 4cm)
#if plot == none [Plot pending] else [Plot #plot]
"""

PLOT_CELL = """@app.cell
def plot(doubled):
    doubled
    return


if __name__ == "__main__":"""


@pytest.mark.parametrize(
    ("bundle", "placed"),
    (
        ({"image/svg+xml": _svg_output(20)["data"]}, True),
        ({"text/html": "<p>4</p>"}, False),
    ),
    ids=("image", "html"),
)
def test_edit_mode_renders_the_image_a_cell_host_posts(
    notebook_path: Path,
    renders: list[dict[str, Any]],
    bundle: dict[str, str],
    placed: bool,
) -> None:
    _configured(notebook_path)
    source = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        source.replace('if __name__ == "__main__":', PLOT_CELL), encoding="utf-8"
    )
    prepare_view(notebook_path, "report", starter="marimo-studio/typst:default")
    project = load_studio(notebook_path).views["report"]
    project.root.joinpath("main.typ").write_text(CELL_REPORT, encoding="utf-8")
    with build_view_project_sync(project):
        pass
    renders.clear()
    app = _marimo_app(notebook_path)
    _edit_mode(app)

    with TestClient(app) as client:
        revision = client.get("/_marimo-studio/views/report/config").json()["revision"]
        response = client.post(
            "/_marimo-studio/views/report/render",
            json={
                "revision": revision,
                "values": {},
                "outputs": {},
                "cells": {
                    "plot": {
                        "mimetype": "application/vnd.marimo+mimebundle",
                        "data": json.dumps(bundle),
                    }
                },
            },
        )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    expected = {"cell:plot": Representation("image/svg+xml", _svg(20))}
    assert renders == [expected if placed else {}]


def test_edit_mode_renders_posted_outputs_once_per_output(
    notebook: Path,
    renders: list[dict[str, Any]],
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        first = _post(client, "report", {"doubled": 42}, {"chart": _svg_output(20)})
        repeated = _post(client, "report", {"doubled": 42}, {"chart": _svg_output(20)})
        other = _post(client, "report", {"doubled": 42}, {"chart": _svg_output(30)})

    assert first.status_code == other.status_code == 200
    assert repeated.content == first.content
    assert other.content != first.content
    assert [call["chart"] for call in renders] == [
        Representation("image/svg+xml", _svg(20)),
        Representation("image/svg+xml", _svg(30)),
    ]


@pytest.mark.parametrize(
    ("outputs", "error"),
    (
        ({"chart": {"mimetype": "image/svg+xml"}}, "invalid-render-request"),
        ({"total": _svg_output(20)}, "render-target-not-allowed"),
        (
            {"chart": {"mimetype": "text/html", "data": "data:text/html;base64,PGI+"}},
            "render-output-not-accepted",
        ),
    ),
)
def test_posted_outputs_must_be_accepted_outputs_the_view_reads(
    notebook: Path,
    outputs: dict[str, dict[str, str]],
    error: str,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, "report", {}, outputs)

    assert (response.status_code, response.json()["error"]) == (400, error)


def test_an_output_that_cannot_be_decoded_leaves_the_template_default(
    notebook: Path,
    renders: list[dict[str, Any]],
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)
    broken = {"mimetype": "image/png", "data": "data:image/png;base64,%%"}

    with TestClient(app) as client:
        response = _post(client, "report", {"doubled": 1}, {"chart": broken})

    assert response.status_code == 200
    assert renders == [{"doubled": 1}]


@pytest.mark.parametrize(
    ("values", "outputs", "code"),
    (
        ({"doubled": "x" * (8 * 2**20)}, {}, "document-values-too-large"),
        (
            {},
            {
                "chart": {
                    "mimetype": "image/svg+xml",
                    "data": "data:image/svg+xml;base64,"
                    + base64.b64encode(b"x" * (16 * 2**20 + 1)).decode("ascii"),
                }
            },
            "document-outputs-too-large",
        ),
    ),
)
def test_a_render_reads_within_the_document_budgets(
    notebook: Path,
    values: dict[str, Any],
    outputs: dict[str, dict[str, str]],
    code: str,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, "report", values, outputs)

    assert response.status_code == 422
    assert [item["code"] for item in response.json()["diagnostics"]] == [code]


def test_render_failures_report_template_diagnostics(notebook: Path) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, "report", {"doubled": 500})

    assert response.status_code == 422
    (diagnostic,) = response.json()["diagnostics"]
    assert diagnostic["message"] == "assertion failed: doubled is too large"
    assert diagnostic["source"]["path"] == "main.typ"
    assert diagnostic["source"]["line"] == 3


@pytest.mark.parametrize(
    ("view", "values", "status", "error"),
    (
        ("report", {"x": 1}, 400, "render-target-not-allowed"),
        ("dashboard", {}, 404, "render-template-missing"),
    ),
)
def test_render_requests_are_scoped_to_the_view_document(
    notebook: Path,
    view: str,
    values: dict[str, Any],
    status: int,
    error: str,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, view, values)

    assert (response.status_code, response.json()["error"]) == (status, error)


def test_values_outside_json_numbers_fail_as_render_diagnostics(
    notebook: Path,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        revision = client.get("/_marimo-studio/views/report/config").json()["revision"]
        response = client.post(
            "/_marimo-studio/views/report/render",
            content=(
                f'{{"revision": "{revision}", "values": {{"doubled": NaN}}, '
                '"outputs": {}, "cells": {}}'
            ),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    (diagnostic,) = response.json()["diagnostics"]
    assert diagnostic["code"] == "render-value-not-json"
    assert diagnostic["message"] == (
        "Documents read JSON values: doubled must not contain NaN or infinity."
    )


def test_published_views_render_only_kernel_values(notebook: Path) -> None:
    with TestClient(_marimo_app(notebook)) as client:
        response = _post(client, "report", {"doubled": 42})

    assert response.status_code == 403
    assert response.json()["error"] == "render-values-unverified"


def test_a_template_damaged_while_serving_marks_the_publication_for_rebuild(
    notebook: Path,
) -> None:
    project = load_studio(notebook).views["report"]
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        revision = client.get("/_marimo-studio/views/report/config").json()["revision"]
        (template,) = project.root.glob(".artifacts/**/template/main.typ")
        template.write_text("#panic()\n", encoding="utf-8")
        response = client.post(
            "/_marimo-studio/views/report/render",
            json={
                "revision": revision,
                "values": {"doubled": 42},
                "outputs": {},
                "cells": {},
            },
        )

    assert response.status_code == 422
    state = read_build_state(project, "development")
    assert state.phase == "stale"
    assert state.diagnostics[0].code == "artifact-integrity-failed"
