"""Verify one separately packaged provider against the installed Studio SDK."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import marimo_studio
from marimo_studio.view_providers.testing import check_provider

_DISTRIBUTION = "marimo-studio-e2e-provider"
_NOTEBOOK = """import marimo

app = marimo.App()


@app.cell
def _():
    metric = 42
    title = "ready"
    title
    return metric, title


if __name__ == "__main__":
    app.run()
"""


def verify() -> None:
    with TemporaryDirectory() as directory:
        notebook = Path(directory, "external.py")
        notebook.write_text(_NOTEBOOK, encoding="utf-8")
        (report,) = check_provider(f"{_DISTRIBUTION}/report", notebook=notebook)
    page = report.published[PurePosixPath("index.html")].decode()
    if 'data-external-build="ready"' not in page:
        raise AssertionError("External report build did not run")
    (web,) = check_provider(f"{_DISTRIBUTION}/web")
    if PurePosixPath("src/scripts/app.js") not in web.published:
        raise AssertionError("External web build did not publish its scripts")


def verify_types() -> None:
    installed = distribution(_DISTRIBUTION)
    root = Path(str(installed.locate_file(""))).resolve()
    sources = sorted(
        str(Path(str(installed.locate_file(item))).resolve())
        for item in installed.files or ()
        if item.parts[:1] == ("fixture_provider",) and item.suffix == ".py"
    )
    if not sources:
        raise AssertionError("External provider distribution has no Python sources")
    subprocess.run(
        [
            "ty",
            "check",
            "--python",
            sys.executable,
            "--extra-search-path",
            str(Path(marimo_studio.__file__).resolve().parents[1]),
            "--extra-search-path",
            str(root),
            *sources,
        ],
        check=True,
    )


if __name__ == "__main__":
    verify()
    if "--typecheck" in sys.argv[1:]:
        verify_types()
