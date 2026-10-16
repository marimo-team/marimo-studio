from __future__ import annotations

import json
from pathlib import Path

import pytest
from marimo_export import StateSpace

from marimo_studio._delivery.export import preflight_view
from marimo_studio._views.api import prepare_view
from marimo_studio.view_providers import JsonValue

from ..helpers import replace_app_shell

NOTEBOOK = """import marimo

app = marimo.App()


@app.cell
def controls():
    import marimo as mo

    level = mo.ui.slider(0, 1, step=0.25, value=0)
    region = mo.ui.dropdown(["north", "south", "east"], value="north")
    mo.hstack([level, region])
    return level, region


@app.cell
def _(level, region):
    summary = f"{region.value} at {level.value}"
    return (summary,)


if __name__ == "__main__":
    app.run()
"""


def _view(notebook: Path, matrix: dict[str, list[JsonValue]]) -> None:
    notebook.write_text(NOTEBOOK, encoding="utf-8")
    root = prepare_view(notebook).root
    document = root / "index.html"
    document.write_text(
        replace_app_shell(
            document.read_text(encoding="utf-8"),
            '<marimo-cell name="controls"></marimo-cell>'
            '<output mo-value="summary"></output>',
        ),
        encoding="utf-8",
    )
    root.joinpath("states.yaml").write_text(
        json.dumps(StateSpace(default_state="matrix-000000", matrix=matrix).to_value()),
        encoding="utf-8",
    )


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_preflight_warns_about_control_values_no_prepared_state_holds(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    _view(notebook, {"level": [0, 0.5, 1], "region": [["north"], ["south"]]})

    report = preflight_view(notebook, runtime="zero-python", prepare_timeout=120.0)

    assert report.ok
    warnings = {
        issue.reference: issue
        for issue in report.issues
        if issue.code == "prepared-states-skip-control-values"
    }
    assert set(warnings) == {"level", "region"}
    assert "skip 2 values" in warnings["level"].message
    assert "0.25, 0.75" in warnings["level"].message
    assert "skip 1 value" in warnings["region"].message
    assert '["east"]' in warnings["region"].message
    assert warnings["level"].source.path.as_posix() == "states.yaml"


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_preflight_is_quiet_when_prepared_states_cover_every_control_value(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    _view(
        notebook,
        {
            "level": [0, 0.25, 0.5, 0.75, 1],
            "region": [["north"], ["south"], ["east"]],
        },
    )

    report = preflight_view(notebook, runtime="zero-python", prepare_timeout=120.0)

    assert [
        issue
        for issue in report.issues
        if issue.code == "prepared-states-skip-control-values"
    ] == []
