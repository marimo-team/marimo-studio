from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.testclient import TestClient

from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._projections.runtime_records import ValueReadError
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace import load_studio
from marimo_studio.errors._internal import RuntimeSyncRequiredError
from marimo_studio.view_providers import (
    ProjectDiagnostic,
    ProviderAvailability,
    RenderRequest,
    RenderResult,
    Representation,
)
from marimo_studio.view_providers._builtin import typst as typst_module
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
RENDER_URL = "/_marimo-studio/views/report/render"
SESSION = "s_reader"


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

    def counted(request: RenderRequest) -> RenderResult:
        cells = {f"cell:{name}": media for name, media in request.cells.items()}
        calls.append({**request.values, **request.outputs, **cells})
        return render(typst, request)

    monkeypatch.setattr(typst, "render", counted)
    return calls


def _revision(client: TestClient, view: str = "report") -> str:
    return client.get(f"/_marimo-studio/views/{view}/config").json()["revision"]


def _post(
    client: TestClient,
    view: str,
    values: dict[str, Any],
    outputs: dict[str, dict[str, str]] | None = None,
    *,
    render: str = "main.typ",
) -> Any:
    return client.post(
        f"/_marimo-studio/views/{view}/render",
        json={
            "revision": _revision(client, view),
            "render": render,
            "values": values,
            "outputs": outputs or {},
            "cells": {},
        },
    )


def test_edit_mode_renders_posted_inputs_once_per_input_set(
    notebook: Path,
    renders: list[dict[str, Any]],
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        first = _post(client, "report", {"doubled": 42})
        repeated = _post(client, "report", {"doubled": 42.0})
        other = _post(client, "report", {"doubled": 7})

    assert first.status_code == other.status_code == 200
    body = first.json()
    assert body["render"] == "main.typ"
    assert body["main"] == "main.pdf"
    assert body["preview"] is None
    assert [(item["path"], item["mediaType"]) for item in body["files"]] == [
        ("main.pdf", "application/pdf")
    ]
    assert repeated.json()["bundle"] == body["bundle"]
    assert other.json()["bundle"] != body["bundle"]
    assert renders == [{"doubled": 42}, {"doubled": 7}]


def test_rendered_files_are_served_with_byte_ranges_to_their_view(
    notebook: Path,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        bundle = _post(client, "report", {"doubled": 42}).json()["bundle"]
        url = f"/_marimo-studio/views/report/renders/{bundle}/main.pdf"
        full = client.get(url)
        partial = client.get(url, headers={"Range": "bytes=0-3"})
        other_view = client.get(
            f"/_marimo-studio/views/dashboard/renders/{bundle}/main.pdf"
        )
        unknown = client.get(
            f"/_marimo-studio/views/report/renders/{'0' * 64}/main.pdf"
        )

    assert full.status_code == 200
    assert full.headers["content-type"] == "application/pdf"
    assert full.content.startswith(b"%PDF-")
    assert partial.status_code == 206
    assert partial.content == b"%PDF"
    assert other_view.status_code == 404
    assert unknown.status_code == 404


def test_concurrent_identical_renders_share_one_bundle(
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
    assert len({response.json()["bundle"] for response in responses}) == 1
    # Two render workers can start before either finishes. Every request
    # queued behind them reuses the stored bundle.
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
    app = _marimo_app(notebook_path)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.post(
            RENDER_URL,
            json={
                "revision": _revision(client),
                "render": "main.typ",
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
    assert response.json()["absent"] == ([] if placed else ["plot"])
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
    assert repeated.json()["bundle"] == first.json()["bundle"]
    assert other.json()["bundle"] != first.json()["bundle"]
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
def test_posted_outputs_must_be_accepted_outputs_the_render_reads(
    notebook: Path,
    outputs: dict[str, dict[str, str]],
    error: str,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, "report", {}, outputs)

    assert (response.status_code, response.json()["error"]) == (400, error)


def test_an_output_that_cannot_be_decoded_renders_the_template_default(
    notebook: Path,
    renders: list[dict[str, Any]],
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)
    broken = {"mimetype": "image/png", "data": "data:image/png;base64,%%"}

    with TestClient(app) as client:
        response = _post(client, "report", {"doubled": 1}, {"chart": broken})

    assert response.status_code == 200
    assert response.json()["absent"] == ["chart"]
    assert renders == [{"doubled": 1}]


def test_a_render_without_the_provider_requirement_names_its_install_action(
    notebook: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A server started without the typst extra still serves the view a CLI
    # build published, and its compiler subprocess fails to import typst.
    monkeypatch.setattr(
        typst,
        "availability",
        lambda: ProviderAvailability(
            False,
            reason="The typst Python package is not installed.",
            action="Install marimo-studio[typst], then restart marimo.",
        ),
    )
    monkeypatch.setattr(
        typst_module,
        "_run_typst",
        lambda *_: ProjectDiagnostic(
            "typst-compile-failed",
            "error",
            "Typst stopped before it finished main.typ. "
            "ModuleNotFoundError: No module named 'typst'",
            "Fix main.typ, then save it to render again.",
        ),
    )
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, "report", {"doubled": 42})

    assert response.status_code == 422
    (diagnostic,) = response.json()["diagnostics"]
    assert diagnostic["code"] == "provider-unavailable"
    assert "typst Python package is not installed" in diagnostic["message"]
    assert diagnostic["hint"] == "Install marimo-studio[typst], then restart marimo."


@pytest.mark.parametrize(
    ("values", "outputs", "code"),
    (
        ({"doubled": "x" * (8 * 2**20)}, {}, "render-values-too-large"),
        (
            {},
            {
                "chart": {
                    "mimetype": "image/svg+xml",
                    "data": "data:image/svg+xml;base64,"
                    + base64.b64encode(b"x" * (16 * 2**20 + 1)).decode("ascii"),
                }
            },
            "render-outputs-too-large",
        ),
    ),
)
def test_a_render_reads_within_its_input_budgets(
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
    assert response.json()["error"] == "render-failed"
    (diagnostic,) = response.json()["diagnostics"]
    assert "doubled is too large" in diagnostic["message"]
    assert diagnostic["source"]["path"] == "main.typ"
    assert diagnostic["source"]["line"] == 3


@pytest.mark.parametrize(
    ("view", "render", "declared"),
    (
        ("report", "slides.typ", "main.typ"),
        ("dashboard", "main.typ", "none"),
        ("report", "./main.typ", "main.typ"),
        ("report", "chapters/../main.typ", "main.typ"),
        ("report", "/main.typ", "main.typ"),
        ("report", "main.typ/", "main.typ"),
        ("report", "", "main.typ"),
    ),
    ids=(
        "undeclared",
        "page-view",
        "current-segment",
        "parent-segment",
        "absolute",
        "trailing-slash",
        "empty",
    ),
)
def test_a_render_the_view_does_not_declare_is_not_found(
    notebook: Path,
    view: str,
    render: str,
    declared: str,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, view, {}, render=render)

    assert response.status_code == 404
    assert response.json()["error"] == "render-unknown"
    assert declared in response.json()["hint"]


def test_posted_values_are_scoped_to_the_render_reads(notebook: Path) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _post(client, "report", {"x": 1})

    assert (response.status_code, response.json()["error"]) == (
        400,
        "render-target-not-allowed",
    )


def test_values_outside_json_numbers_fail_as_render_diagnostics(
    notebook: Path,
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.post(
            RENDER_URL,
            content=(
                f'{{"revision": "{_revision(client)}", "render": "main.typ", '
                '"values": {"doubled": NaN}, "outputs": {}, "cells": {}}'
            ),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    (diagnostic,) = response.json()["diagnostics"]
    assert diagnostic["code"] == "render-value-not-json"
    assert "doubled" in diagnostic["message"]


@pytest.mark.parametrize(
    "body",
    (
        {"render": "main.typ"},
        {"revision": "r", "render": "main.typ", "values": {}},
        {"revision": "r", "render": 1},
    ),
    ids=("no-revision", "partial-inputs", "render-not-text"),
)
def test_render_requests_name_a_revision_and_a_render(
    notebook: Path, body: dict[str, Any]
) -> None:
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = client.post(RENDER_URL, json=body)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid-render-request"


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
        revision = _revision(client)
        (template,) = project.artifacts.glob("**/template/main.typ")
        template.write_text("#panic()\n", encoding="utf-8")
        response = client.post(
            RENDER_URL,
            json={
                "revision": revision,
                "render": "main.typ",
                "values": {"doubled": 42},
                "outputs": {},
                "cells": {},
            },
        )

    assert response.status_code == 422
    assert response.json()["diagnostics"][0]["code"] == "artifact-integrity-failed"
    state = read_build_state(project, "development")
    assert state.phase == "stale"
    assert state.diagnostics[0].code == "artifact-integrity-failed"


KERNEL_REPORT = """#import "marimo.typ": marimo_output, marimo_value
Total #marimo_value("doubled", default: 0)
#marimo_output("x", width: 4cm)
"""


@pytest.fixture
def kernel_notebook(notebook: Path) -> Path:
    project = load_studio(notebook).views["report"]
    project.root.joinpath("main.typ").write_text(KERNEL_REPORT, encoding="utf-8")
    with build_view_project_sync(project):
        pass
    return notebook


class _KernelReads:
    """Stand in for one reader's kernel session and record what Studio reads."""

    def __init__(
        self,
        generations: list[int],
        *,
        errors: dict[str, ValueReadError] | None = None,
    ) -> None:
        self.generations = generations
        self.errors = errors or {}
        self.readers: list[str | None] = []
        # How many outputs each render_outputs call requested and kept active.
        self.output_calls: list[tuple[int, int]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from marimo_studio._compat.server.session_state import PrivateSessionState

        ownership = PrivateSessionState.ownership
        exists = PrivateSessionState.exists
        live_cells = PrivateSessionState.live_cells

        def owned(state: Any, context: Any, session_id: str) -> Any:
            return (
                "current"
                if session_id == SESSION
                else ownership(state, context, session_id)
            )

        def alive(state: Any, context: Any, session_id: str) -> bool:
            return session_id == SESSION or exists(state, context, session_id)

        async def cells(state: Any, context: Any, session_id: str | None) -> Any:
            if session_id != SESSION:
                return await live_cells(state, context, session_id)
            generation = self.generations.pop(0) if len(self.generations) > 1 else 1
            return SimpleNamespace(
                execution_pending=False, execution_generation=generation
            )

        host = "marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost"
        monkeypatch.setattr(PrivateSessionState, "ownership", owned)
        monkeypatch.setattr(PrivateSessionState, "exists", alive)
        monkeypatch.setattr(PrivateSessionState, "live_cells", cells)
        monkeypatch.setattr(f"{host}.read_values", self.read_values)
        monkeypatch.setattr(f"{host}.render_outputs", self.render_outputs)
        monkeypatch.setattr(
            "marimo_studio._server.presentation.render_routes.runtime_cell_bindings",
            lambda *_args: {},
        )

    async def read_values(self, *_args: object, **kwargs: Any) -> SimpleNamespace:
        self.readers.append(kwargs["reader"])
        if self.errors:
            return SimpleNamespace(values={}, errors=self.errors)
        return SimpleNamespace(
            values={"doubled": {"codec": "json-v1", "value": 42}}, errors={}
        )

    async def render_outputs(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> SimpleNamespace:
        *_, projections, active = args
        self.readers.append(kwargs["reader"])
        self.output_calls.append((len(projections), len(active)))
        if not projections:
            return SimpleNamespace(outputs={})
        chart = _svg_output(20)
        output = SimpleNamespace(mimetype=chart["mimetype"], data=chart["data"])
        return SimpleNamespace(outputs={"x": output})


def _kernel_render(client: TestClient, *, session: str | None = SESSION) -> Any:
    return client.post(
        RENDER_URL,
        headers={"Marimo-Session-Id": session} if session is not None else {},
        json={"revision": _revision(client), "render": "main.typ"},
    )


@pytest.mark.parametrize("edit", (True, False), ids=("edit", "run"))
def test_a_named_render_reads_its_inputs_from_the_reader_kernel(
    kernel_notebook: Path,
    renders: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    edit: bool,
) -> None:
    kernel = _KernelReads([1])
    kernel.install(monkeypatch)
    app = _marimo_app(kernel_notebook)
    if edit:
        _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client)

    assert response.status_code == 200, response.text
    assert response.json()["absent"] == []
    assert renders == [{"doubled": 42, "x": Representation("image/svg+xml", _svg(20))}]
    assert set(kernel.readers) == {f"{SESSION}:render:main.typ"}


def test_a_render_reads_an_undefined_value_as_absent(
    notebook: Path,
    renders: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = load_studio(notebook).views["report"]
    project.root.joinpath("main.typ").write_text(
        KERNEL_REPORT + '#marimo_value("undefined_total", default: 0)\n',
        encoding="utf-8",
    )
    with build_view_project_sync(project):
        pass
    _KernelReads([1]).install(monkeypatch)
    app = _marimo_app(notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client)

    assert response.status_code == 200, response.text
    assert response.json()["absent"] == ["undefined_total"]
    assert renders == [{"doubled": 42, "x": Representation("image/svg+xml", _svg(20))}]


def test_a_render_releases_the_kernel_outputs_it_read(
    kernel_notebook: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _KernelReads([1])
    kernel.install(monkeypatch)
    app = _marimo_app(kernel_notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client)

    assert response.status_code == 200, response.text
    assert kernel.output_calls == [(1, 1), (0, 0)]


def test_a_named_render_waits_for_the_reader_session(
    kernel_notebook: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _KernelReads([1]).install(monkeypatch)
    app = _marimo_app(kernel_notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client, session=None)

    assert response.status_code == 409
    assert response.json()["error"] == "session-unavailable"
    assert response.json()["transient"] is True


def test_a_capture_that_spans_a_notebook_run_is_retried_then_reported(
    kernel_notebook: Path,
    renders: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The notebook runs between every pair of snapshots.
    _KernelReads(list(range(1, 100))).install(monkeypatch)
    monkeypatch.setattr(
        "marimo_studio._server.presentation.render_routes._CAPTURE_DELAYS",
        (0.0, 0.0, 0.0),
    )
    app = _marimo_app(kernel_notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client)

    assert response.status_code == 409
    assert response.json()["error"] == "render-inputs-unsettled"
    assert response.json()["transient"] is True
    assert renders == []


def test_a_kernel_value_without_a_json_form_fails_the_render(
    kernel_notebook: Path,
    renders: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = ValueReadError("not-json-serializable", "A model has no JSON form.")
    _KernelReads([1], errors={"doubled": problem}).install(monkeypatch)
    app = _marimo_app(kernel_notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client)

    assert response.status_code == 422
    assert [item["code"] for item in response.json()["diagnostics"]] == [
        "render-value-not-json"
    ]
    assert renders == []


def test_a_capture_reports_cells_that_need_running_at_once(
    kernel_notebook: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _KernelReads([1]).install(monkeypatch)

    def stale(*_args: object) -> dict[str, str]:
        raise RuntimeSyncRequiredError

    monkeypatch.setattr(
        "marimo_studio._server.presentation.render_routes.runtime_cell_bindings",
        stale,
    )
    app = _marimo_app(kernel_notebook)
    _edit_mode(app)

    with TestClient(app) as client:
        response = _kernel_render(client)

    assert response.status_code == 409
    assert response.json()["error"] == "runtime-sync-required"
    assert "transient" not in response.json()
