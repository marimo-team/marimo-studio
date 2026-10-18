"""Run copyable documentation examples through the APIs they document."""

from __future__ import annotations

import ast
import importlib
import sys
from collections.abc import Iterator
from importlib.metadata import metadata
from pathlib import Path, PurePosixPath

import pytest
from packaging.specifiers import SpecifierSet

from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio.view_providers.testing import check_provider

GUIDE = Path("docs/guide/view-providers.md")


def _documentation_paths() -> tuple[Path, ...]:
    paths = {
        Path("README.md"),
        Path("packages/marimo-studio/README.md"),
        *Path("docs").rglob("*.md"),
        *Path("skills/marimo-studio").rglob("*.md"),
    }
    return tuple(sorted(path for path in paths if path.is_file()))


def _python_blocks(document: str) -> tuple[str, ...]:
    sections = document.split("```python\n")[1:]
    return tuple(section.split("\n```", 1)[0] for section in sections)


def _guide_module(after: str) -> str:
    """Return the first Python block that follows ``after`` in the guide."""
    document = GUIDE.read_text(encoding="utf-8")
    return _python_blocks(document.split(after, 1)[1])[0]


@pytest.fixture
def acme_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    package = tmp_path / "acme_views"
    package.mkdir()
    (package / "__init__.py").write_text(
        _guide_module("Replace `src/acme_views/__init__.py` with:"),
        encoding="utf-8",
    )
    (package / "card.py").write_text(
        _guide_module("`src/acme_views/card.py`:"),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield
    for name in [
        name for name in sys.modules if name.partition(".")[0] == "acme_views"
    ]:
        del sys.modules[name]


def test_every_python_example_compiles() -> None:
    compiled = 0
    for path in _documentation_paths():
        for block in _python_blocks(path.read_text(encoding="utf-8")):
            compile(block, str(path), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            compiled += 1
    assert compiled > 0


@pytest.mark.parametrize(
    "notebook", sorted(Path("examples").glob("*.py")), ids=lambda path: path.stem
)
def test_example_notebook_admits_only_python_versions_studio_installs_on(
    notebook: Path,
) -> None:
    # A sandboxed kernel installs the running Studio, and pixi solves for the
    # newest Python that requires-python admits.
    studio = SpecifierSet(metadata("marimo-studio")["Requires-Python"])
    document = read_notebook_metadata(notebook)
    assert document is not None
    declared = SpecifierSet(str(document["requires-python"]))

    admitted = [f"3.{minor}" for minor in range(8, 30) if f"3.{minor}" in declared]

    assert admitted
    assert [version for version in admitted if version not in studio] == []


@pytest.mark.usefixtures("acme_views")
def test_guide_report_provider_publishes_the_notebook_cells() -> None:
    provider = importlib.import_module("acme_views").provider

    (view,) = check_provider(provider)

    page = view.published[PurePosixPath("index.html")].decode()
    assert '<marimo-cell name="' in page
    assert "data-marimo-studio-site" in page


@pytest.mark.usefixtures("acme_views")
def test_guide_card_provider_renders_the_report_total() -> None:
    provider = importlib.import_module("acme_views.card").provider

    (view,) = check_provider(provider, values={"report.total": 1234})

    card = view.renders[PurePosixPath("card.svg")]
    assert card.media_types == {PurePosixPath("card.svg"): "image/svg+xml"}
    assert b"Total: 1234" in card.files[card.main]
    assert [region.reads for region in card.regions] == [("report.total",)]
