from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import marimo
import pytest

import marimo_studio._validation.static as checks_module
import marimo_studio._views.inspection as inspection_module
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    RenderedOutput,
    RuntimeCell,
    RuntimeProbe,
    ValueReadError,
    ValueReadResult,
)
from marimo_studio._validation.service import prepare_validation
from marimo_studio._validation.static import check_runtime_studio, check_studio
from marimo_studio._views.api import bind_cell, prepare_view
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._workspace import load_studio

from .workspace_test_support import (
    _shell,
)


def test_validation_preserves_mount_inspection_cleanup_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise ProcessCleanupError("mount inspection process survived")

    monkeypatch.setattr(inspection_module, "inspect_view_project_sync", fail)

    with pytest.raises(ProcessCleanupError, match="mount inspection process survived"):
        asyncio.run(
            prepare_validation(
                load_studio(notebook_path),
                view_name="dashboard",
            )
        )


def test_runtime_check_scopes_values_to_the_selected_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    bound = bind_cell(studio, "result", 1)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<marimo-cell name="result"></marimo-cell>'
        '<span mo-value="doubled.missing"></span>',
    )
    _shell(studio, "executive", '<span mo-value="x"></span>')
    captured: dict[str, object] = {}

    async def probe(*_: object, **kwargs: object) -> RuntimeProbe:
        captured.update(kwargs)
        return RuntimeProbe(
            cells={
                bound.cell.runtime_id: RuntimeCell(
                    status="idle",
                    outputs=(),
                    errors=(),
                )
            },
            values=ValueReadResult(
                values={},
                errors={
                    "doubled.missing": ValueReadError(
                        "value-path-unavailable",
                        "Missing key",
                    )
                },
            ),
            outputs=OutputRenderResult(outputs={}, errors={}),
        )

    monkeypatch.setattr(
        checks_module,
        "create_runtime_probe",
        lambda: probe,
    )
    results = asyncio.run(
        check_runtime_studio(load_studio(notebook_path), view_name="dashboard")
    )
    current = resolve_studio(
        load_studio(notebook_path),
        view_name="dashboard",
    ).aliases["result"]
    value_projection = next(
        projection
        for projection in (
            resolve_studio(
                load_studio(notebook_path),
                view_name="dashboard",
            )
            .view("dashboard")
            .projections
        )
        if projection.request.target == "doubled.missing"
    )

    assert captured["variables"] == ("doubled.missing",)
    assert {result.name for result in results if result.status == "fail"} == {
        "runtime-cell:result",
        "runtime-value:doubled.missing",
    }
    failures = {result.name: result for result in results if result.status == "fail"}
    assert failures["runtime-cell:result"].code == "projected-cell-empty"
    assert failures["runtime-cell:result"].details == {
        "projection": "cell",
        "target": "result",
        "source": {
            "path": str(notebook_path),
            "line": current.source.start_line,
            "column": 1,
        },
        "hint": "Return a display value from the cell or remove its projection.",
        "view": "dashboard",
    }
    assert failures["runtime-value:doubled.missing"].code == ("value-path-unavailable")
    assert failures["runtime-value:doubled.missing"].message == "Missing key"
    assert failures["runtime-value:doubled.missing"].details is not None
    assert failures["runtime-value:doubled.missing"].details["target"] == (
        "doubled.missing"
    )
    assert failures["runtime-value:doubled.missing"].details["projection"] == "value"
    assert failures["runtime-value:doubled.missing"].details["view"] == "dashboard"
    value_details = failures["runtime-value:doubled.missing"].details
    assert value_details["source"] == {
        "path": str(
            load_studio(notebook_path).views["dashboard"].root
            / value_projection.source.path
        ),
        "line": value_projection.source.line,
        "column": value_projection.source.column,
    }
    assert value_details["producer"] == str(value_projection.producer)
    assert value_details["dependency_closure"] == [
        str(ref) for ref in value_projection.dependency_closure
    ]
    assert value_details["siteId"] == value_projection.request.site_id
    assert value_details["hint"] == (
        "Fix the mo-value selector in the view source or the value shape "
        "in Marimo, then rerun the check."
    )


def test_runtime_check_reports_rich_output_format_failures(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(studio, "dashboard", '<marimo-output value="doubled"></marimo-output>')
    captured: dict[str, object] = {}

    async def probe(*_: object, **kwargs: object) -> RuntimeProbe:
        captured.update(kwargs)
        return RuntimeProbe(
            cells={},
            values=ValueReadResult(values={}, errors={}),
            outputs=OutputRenderResult(
                outputs={},
                errors={
                    "doubled": ValueReadError(
                        "output-format-error",
                        "The rich representation failed",
                    )
                },
            ),
        )

    monkeypatch.setattr(
        checks_module,
        "create_runtime_probe",
        lambda: probe,
    )
    results = asyncio.run(
        check_runtime_studio(load_studio(notebook_path), view_name="dashboard")
    )
    failure = next(result for result in results if result.status == "fail")

    assert captured["variables"] == ()
    assert captured["output_selector_groups"] == (("doubled",),)
    assert failure.name == "runtime-output:doubled"
    assert failure.code == "output-format-error"
    assert failure.message == "The rich representation failed"
    assert failure.details is not None
    assert failure.details["projection"] == "output"
    assert failure.details["target"] == "doubled"
    assert failure.details["view"] == "dashboard"


def test_runtime_check_propagates_output_response_errors(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(studio, "dashboard", '<marimo-output value="doubled"></marimo-output>')

    async def probe(*_: object, **__: object) -> RuntimeProbe:
        return RuntimeProbe(
            cells={},
            values=ValueReadResult(values={}, errors={}),
            outputs=OutputRenderResult(
                outputs={},
                errors={
                    "*": ValueReadError(
                        "response-too-large",
                        "The output response exceeds the aggregate byte limit.",
                    )
                },
            ),
        )

    monkeypatch.setattr(
        checks_module,
        "create_runtime_probe",
        lambda: probe,
    )
    results = asyncio.run(
        check_runtime_studio(load_studio(notebook_path), view_name="dashboard")
    )
    failure = next(result for result in results if result.status == "fail")

    assert failure.name == "runtime-output:doubled"
    assert failure.code == "response-too-large"
    assert failure.message == "The output response exceeds the aggregate byte limit."


def test_runtime_check_keeps_output_request_groups_within_each_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "many_outputs.py"
    names = [f"output_{index}" for index in range(102)]
    assignments = "\n".join(f"    {name} = {index}" for index, name in enumerate(names))
    returned = ", ".join(names)
    notebook.write_text(
        f'''import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
{assignments}
    return {returned}


if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    prepare_view(notebook)
    prepare_view(notebook, "executive")
    studio = load_studio(notebook)
    _shell(
        studio,
        "dashboard",
        "".join(
            f'<marimo-output value="{name}"></marimo-output>' for name in names[:51]
        ),
    )
    _shell(
        studio,
        "executive",
        "".join(
            f'<marimo-output value="{name}"></marimo-output>' for name in names[51:]
        ),
    )
    captured: dict[str, object] = {}

    async def probe(*_: object, **kwargs: object) -> RuntimeProbe:
        captured.update(kwargs)
        return RuntimeProbe(
            cells={},
            values=ValueReadResult(values={}, errors={}),
            outputs=OutputRenderResult(
                outputs={
                    name: RenderedOutput(
                        owner_cell_id=f"owner-{name}",
                        mimetype="text/plain",
                        data=str(index),
                        timestamp=1,
                    )
                    for index, name in enumerate(names)
                },
                errors={},
            ),
        )

    monkeypatch.setattr(
        checks_module,
        "create_runtime_probe",
        lambda: probe,
    )
    results = asyncio.run(check_runtime_studio(load_studio(notebook)))

    groups = cast(tuple[tuple[str, ...], ...], captured["output_selector_groups"])
    assert tuple(len(group) for group in groups) == (51, 51)
    assert all(result.status == "pass" for result in results)


def test_runtime_check_reports_disabled_projection_causes(tmp_path: Path) -> None:
    notebook = tmp_path / "disabled.py"
    notebook.write_text(
        f"""\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell(disabled=True)
def disabled_cell():
    blocked = 1
    blocked
    return (blocked,)


@app.cell
def dependent_cell(blocked):
    result = blocked + 1
    result
    return (result,)


if __name__ == "__main__":
    app.run()
""",
        encoding="utf-8",
    )
    prepare_view(notebook)
    studio = load_studio(notebook)
    _shell(
        studio,
        "dashboard",
        '<marimo-cell name="disabled_cell"></marimo-cell>'
        '<marimo-cell name="dependent_cell"></marimo-cell>',
    )

    results = asyncio.run(
        check_runtime_studio(load_studio(notebook), view_name="dashboard")
    )
    failures = {result.name: result for result in results if result.status == "fail"}

    assert failures["runtime-cell:disabled_cell"].code == "cell-disabled"
    assert failures["runtime-cell:disabled_cell"].message == (
        "Projected cell is disabled"
    )
    disabled_details = failures["runtime-cell:disabled_cell"].details
    assert disabled_details is not None
    assert disabled_details["hint"] == (
        "Enable the cell in Marimo or remove its projection."
    )
    assert failures["runtime-cell:dependent_cell"].code == "cell-disabled"
    assert failures["runtime-cell:dependent_cell"].message == (
        "Projected cell has a disabled upstream dependency"
    )
    dependent_details = failures["runtime-cell:dependent_cell"].details
    assert dependent_details is not None
    assert dependent_details["hint"] == (
        "Enable the disabled upstream cell in Marimo or remove this projection."
    )


def test_runtime_check_reports_the_original_cell_exception(tmp_path: Path) -> None:
    notebook = tmp_path / "broken.py"
    notebook.write_text(
        f"""\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def broken():
    raise ValueError("bad input")


if __name__ == "__main__":
    app.run()
""",
        encoding="utf-8",
    )
    prepare_view(notebook)
    studio = load_studio(notebook)
    _shell(studio, "dashboard", '<marimo-cell name="broken"></marimo-cell>')

    results = asyncio.run(
        check_runtime_studio(load_studio(notebook), view_name="dashboard")
    )
    failure = next(result for result in results if result.status == "fail")

    assert failure.code == "cell-execution-error"
    assert "ValueError: bad input" in failure.message


def test_runtime_check_ignores_plain_htmx_routes(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<button hx-get="./_marimo-studio/views/dashboard/cells/result">'
        "Load result"
        "</button>",
    )
    captured: dict[str, object] = {}

    async def probe(*_: object, **kwargs: object) -> RuntimeProbe:
        captured.update(kwargs)
        return RuntimeProbe(
            cells={},
            values=ValueReadResult(values={}, errors={}),
            outputs=OutputRenderResult(outputs={}, errors={}),
        )

    monkeypatch.setattr(
        checks_module,
        "create_runtime_probe",
        lambda: probe,
    )
    results = asyncio.run(
        check_runtime_studio(load_studio(notebook_path), view_name="dashboard")
    )

    assert captured["cell_ids"] == ()
    assert [result.name for result in results] == ["runtime"]
    assert results[0].status == "pass"


def test_selected_view_check_isolated_from_other_templates(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    _shell(studio, "dashboard", '<span mo-value="missing"></span>')

    selected = check_studio(load_studio(notebook_path), view_name="executive")
    all_views = check_studio(load_studio(notebook_path))

    assert all(result.status == "pass" for result in selected.checks)
    assert any(result.status == "fail" for result in all_views.checks)
