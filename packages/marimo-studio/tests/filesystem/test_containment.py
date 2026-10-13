from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._filesystem.paths import is_within

from ..helpers import link_directory

pytestmark = pytest.mark.supported_python


def test_a_directory_contains_itself_and_its_descendants(tmp_path: Path) -> None:
    views = tmp_path / "views"
    (views / "dashboard").mkdir(parents=True)

    assert is_within(views, views)
    assert is_within(views / "dashboard", views)
    assert is_within(views / "dashboard" / "missing.html", views)


def test_a_sibling_with_the_same_prefix_is_outside(tmp_path: Path) -> None:
    (tmp_path / "views").mkdir()
    (tmp_path / "views-old" / "dashboard").mkdir(parents=True)

    assert not is_within(tmp_path / "views-old" / "dashboard", tmp_path / "views")
    assert not is_within(tmp_path, tmp_path / "views")


def test_a_missing_directory_compares_by_path(tmp_path: Path) -> None:
    missing = tmp_path / "views"

    assert is_within(missing / "dashboard", missing)
    assert not is_within(tmp_path / "views-old", missing)


def test_a_path_through_a_link_into_the_directory_is_inside(tmp_path: Path) -> None:
    views = tmp_path / "views"
    (views / "dashboard").mkdir(parents=True)
    link = tmp_path / "linked"
    link_directory(views, link)

    assert is_within(link / "dashboard", views)
    assert is_within(views / "dashboard", link)
