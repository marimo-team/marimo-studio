from __future__ import annotations

import importlib
import sys
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio.view_providers import ProviderStarter, StarterContext
from marimo_studio.view_providers._bundled._starters import (
    starter_catalog,
    starter_files,
)


def _fixture_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str],
) -> str:
    package = tmp_path / "bundled_starter_fixture"
    package.mkdir()
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    for relative, content in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(package.name, None)
    importlib.invalidate_caches()
    return package.name


def _starter() -> ProviderStarter:
    return ProviderStarter(
        key="default",
        title="Fixture",
        summary="A packaged starter fixture.",
        documents=(PurePosixPath("index.html"),),
    )


def test_bundled_starter_rejects_overlapping_shared_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _fixture_package(
        tmp_path,
        monkeypatch,
        {
            "starters/_shared/index.html": "shared",
            "starters/default/index.html": "default",
        },
    )
    starter = _starter()

    with pytest.raises(ValueError, match=r"defines 'index\.html' more than once"):
        starter_files(
            package,
            starter_catalog(starter),
            starter,
            StarterContext("dashboard", "analysis"),
        )
