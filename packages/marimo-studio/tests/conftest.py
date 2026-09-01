from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import marimo
import pytest

import marimo_studio._delivery.assets as assets_module
from marimo_studio._compat.layout import MARIMO_RELEASE_COMMIT
from marimo_studio.view_providers._bundled._deno import runtime as deno_runtime

from .helpers import notebook_source


@pytest.fixture(autouse=True, scope="session")
def runtime_assets(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    assets = tmp_path_factory.mktemp("runtime-assets")
    for name in (
        "runtime.js",
        "runtime.css",
        "dev-reload.js",
        "studio.js",
        "studio.css",
    ):
        (assets / name).write_text("", encoding="utf-8")
    (assets / "build-meta.json").write_text(
        json.dumps(
            {
                "marimo": {
                    "version": marimo.__version__,
                    "commit": MARIMO_RELEASE_COMMIT,
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    licenses = assets / "licenses"
    licenses.joinpath("marimo").mkdir(parents=True)
    licenses.joinpath("marimo-studio").mkdir()
    licenses.joinpath("THIRD_PARTY_NOTICES.json").write_text("{}\n", encoding="utf-8")
    licenses.joinpath("THIRD_PARTY_NOTICES.txt").write_text(
        "notices\n", encoding="utf-8"
    )
    licenses.joinpath("THIRD_PARTY_LICENSES.txt").write_text(
        "licenses\n", encoding="utf-8"
    )
    licenses.joinpath("marimo", "LICENSE").write_text("license\n", encoding="utf-8")
    licenses.joinpath("marimo-studio", "LICENSE").write_text(
        "license\n", encoding="utf-8"
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)
    yield assets
    monkeypatch.undo()


@pytest.fixture
def notebook_path(tmp_path: Path) -> Path:
    path = tmp_path / "analysis.py"
    path.write_text(
        notebook_source(tmp_path / "cell-executed"),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="session")
def deno_test_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("deno-cache")


@pytest.fixture
def shared_deno_test_cache(
    monkeypatch: pytest.MonkeyPatch,
    deno_test_cache: Path,
) -> None:
    ensure_cache_directory = deno_runtime.ensure_cache_directory
    monkeypatch.setattr(
        deno_runtime,
        "ensure_cache_directory",
        lambda _root, relative: ensure_cache_directory(
            deno_test_cache.resolve(),
            relative,
        ),
    )
