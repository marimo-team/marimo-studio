from __future__ import annotations

import json
from pathlib import Path

import marimo
import pytest

import marimo_studio._assets as assets_module

from .helpers import notebook_source


@pytest.fixture(autouse=True)
def runtime_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    assets = tmp_path / "runtime-assets"
    assets.mkdir()
    for name in (
        "runtime.js",
        "runtime.css",
        "dev-reload.js",
        "studio.js",
        "studio.css",
    ):
        (assets / name).write_text("", encoding="utf-8")
    (assets / "build-meta.json").write_text(
        json.dumps({"marimo": {"version": marimo.__version__}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)
    return assets


@pytest.fixture
def notebook_path(tmp_path: Path) -> Path:
    path = tmp_path / "analysis.py"
    path.write_text(
        notebook_source(tmp_path / "cell-executed"),
        encoding="utf-8",
    )
    return path
