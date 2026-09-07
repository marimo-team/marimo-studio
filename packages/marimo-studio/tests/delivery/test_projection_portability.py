from __future__ import annotations

from pathlib import Path

import marimo
import pytest

from marimo_studio._delivery.export import export_view
from marimo_studio._views.api import prepare_view
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers._bundled import _deno

from ..helpers import replace_app_shell

_PREPARE_TIMEOUT = 120.0


@pytest.mark.deno
@pytest.mark.usefixtures("shared_deno_test_cache")
@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_zero_python_reports_a_dynamic_projection_before_preparation(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    setup = prepare_view(
        notebook_path,
        starter="marimo-studio/react:default",
    )
    setup.root.joinpath("src/App.tsx").write_text(
        """/// <reference path="./marimo-studio.d.ts" />

const selected = window.location.hash.slice(1) || "cell-2";

export const App = () => (
  <main>
    <marimo-cell name={selected} data-marimo-allow="*" />
  </main>
);
""",
        encoding="utf-8",
    )

    with pytest.raises(PublicationError) as raised:
        export_view(
            notebook_path,
            tmp_path / "site",
            runtime="zero-python",
            prepare_timeout=_PREPARE_TIMEOUT,
        )

    assert raised.value.code == "zero-python-projection-dynamic"
    details = raised.value.diagnostic_details()
    assert details["runtime"] == "zero-python"
    projection = details["projection"]
    assert isinstance(projection, dict)
    assert projection["projection"] == "cell"
    assert projection["status"] == "incompatible"


@pytest.mark.native_process
@pytest.mark.xdist_group("managed-export")
def test_zero_python_attributes_nonportable_functions_to_the_projection(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "table.py"
    notebook.write_text(
        f'''import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    athletes = mo.ui.table([{{"name": "Ada"}}, {{"name": "Grace"}}])
    athletes
    return (athletes,)


if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    setup = prepare_view(notebook)
    document = setup.root / "index.html"
    document.write_text(
        replace_app_shell(
            document.read_text(encoding="utf-8"),
            '<marimo-output value="athletes"></marimo-output>',
        ),
        encoding="utf-8",
    )

    with pytest.raises(PublicationError) as raised:
        export_view(
            notebook,
            tmp_path / "site",
            runtime="zero-python",
            prepare_timeout=_PREPARE_TIMEOUT,
        )

    assert raised.value.code == "zero-python-projection-functions"
    details = raised.value.diagnostic_details()
    assert details["runtime"] == "zero-python"
    assert details["projection"] == "output"
    assert details["target"] == "athletes"
    sources = details["sources"]
    assert isinstance(sources, list) and len(sources) == 1
    assert sources[0]["path"] == "index.html"
    assert sources[0]["line"] > 0
    upstream = details["marimo_export"]
    assert isinstance(upstream, dict)
    assert upstream["code"] == "output_not_portable"
    assert upstream["details"]["functions"]
