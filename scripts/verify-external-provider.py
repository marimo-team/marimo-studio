"""Verify one separately packaged provider against the installed Studio SPI."""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory

import marimo_studio
import marimo_studio.agent as studio

_NOTEBOOK = """import marimo

app = marimo.App()

@app.cell
def title():
    title = "ready"
    title
    return (title,)

if __name__ == "__main__":
    app.run()
"""
_STARTER = "marimo-studio-e2e-provider/report:default"
_WEB_STARTER = "marimo-studio-e2e-provider/web:default"


def installed_provider_sources() -> tuple[Path, ...]:
    installed = distribution("marimo-studio-e2e-provider")
    files = installed.files
    if files is None:
        raise AssertionError("External provider distribution has no file manifest")
    provider_files = tuple(
        sorted(
            Path(str(installed.locate_file(item))).resolve()
            for item in files
            if item.parts[:1] == ("fixture_provider",) and item.suffix == ".py"
        )
    )
    if not provider_files:
        raise AssertionError("External provider distribution has no Python sources")
    return provider_files


async def verify() -> None:
    with TemporaryDirectory() as directory:
        notebook = Path(directory) / "external.py"
        notebook.write_text(_NOTEBOOK, encoding="utf-8")
        workspace = studio.open(notebook=notebook)
        starters = {item.id: item for item in await workspace.starters()}
        if _STARTER not in starters or _WEB_STARTER not in starters:
            raise AssertionError(f"External starter is missing: {sorted(starters)}")
        view = await workspace.create_view("dashboard", starter=starters[_STARTER])
        await view.build()
        inspection = await view.inspect()
        if inspection.provider != "marimo-studio-e2e-provider/report":
            raise AssertionError(f"Unexpected external provider: {inspection.provider}")
        if inspection.publication is None:
            raise AssertionError("External provider did not publish an artifact")
        report_errors = tuple(
            diagnostic
            for diagnostic in inspection.diagnostics
            if diagnostic.severity == "error"
        )
        if report_errors:
            raise AssertionError(f"External report diagnostics: {report_errors}")
        document = await view.read("index.html")
        if "<h1 data-external-provider>Dashboard</h1>" not in document.content:
            raise AssertionError("External provider source was not created")
        web = await workspace.create_view("web", starter=starters[_WEB_STARTER])
        await web.build()
        web_inspection = await web.inspect()
        if web_inspection.provider != "marimo-studio-e2e-provider/web":
            raise AssertionError(f"Unexpected web provider: {web_inspection.provider}")
        if web_inspection.publication is None:
            raise AssertionError("External web provider did not publish an artifact")
        web_errors = tuple(
            diagnostic
            for diagnostic in web_inspection.diagnostics
            if diagnostic.severity == "error"
        )
        if web_errors:
            raise AssertionError(f"External web diagnostics: {web_errors}")
        entry = await web.read("src/index.html")
        script = await web.read("src/scripts/app.js")
        if not entry.content or not script.content:
            raise AssertionError("External web provider documents are unreadable")


def verify_types(provider_sources: tuple[Path, ...]) -> None:
    installed_packages = Path(marimo_studio.__file__).resolve().parents[1]
    provider_packages = Path(
        str(distribution("marimo-studio-e2e-provider").locate_file(""))
    ).resolve()
    subprocess.run(
        [
            "ty",
            "check",
            "--python",
            sys.executable,
            "--extra-search-path",
            str(installed_packages),
            "--extra-search-path",
            str(provider_packages),
            *(str(path) for path in provider_sources),
        ],
        check=True,
    )


def verify_spi_boundary(provider_sources: tuple[Path, ...]) -> None:
    modules: set[str] = set()
    for path in provider_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
    private = sorted(
        module
        for module in modules
        if module.startswith("marimo_studio")
        and module != "marimo_studio.view_providers"
    )
    if private:
        raise AssertionError(
            f"External provider imports outside the public SPI: {private}"
        )


if __name__ == "__main__":
    sources = installed_provider_sources()
    verify_spi_boundary(sources)
    asyncio.run(verify())
    if "--typecheck" in sys.argv[1:]:
        verify_types(sources)
