from __future__ import annotations

import os
from pathlib import Path

import pytest

import marimo_studio._filesystem.files as files
from marimo_studio._filesystem.files import FileTree

from .conftest import entries

pytestmark = [
    pytest.mark.supported_python,
    pytest.mark.skipif(
        os.name == "nt", reason="Windows resolves paths without directory handles"
    ),
]


@pytest.fixture
def swapped(
    tree: FileTree,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Replace ``views`` with a symlink once an operation has resolved it.

    Returns the directory that the operation resolved and the symlink target.
    """
    views = tree.root / "views"
    (views / "dashboard").mkdir(parents=True)
    (views / "dashboard" / "index.html").write_bytes(b"inside")
    outside = tmp_path / "outside"
    (outside / "dashboard").mkdir(parents=True)
    (outside / "dashboard" / "index.html").write_bytes(b"outside")
    resolved = tree.root / "resolved"
    open_directory = files.open_directory

    def swap_after_resolving(
        name: str | Path, *, path: Path, parent: int | None = None
    ) -> int:
        descriptor = open_directory(name, path=path, parent=parent)
        if path == views / "dashboard" and not resolved.exists():
            views.rename(resolved)
            views.symlink_to(outside, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(files, "open_directory", swap_after_resolving)
    return resolved, outside


def test_a_read_uses_the_directory_it_resolved(
    tree: FileTree, swapped: tuple[Path, Path]
) -> None:
    snapshot = tree.read(tree.root / "views" / "dashboard" / "index.html")

    assert snapshot.content == b"inside"


def test_a_write_lands_in_the_directory_it_resolved(
    tree: FileTree, swapped: tuple[Path, Path]
) -> None:
    resolved, outside = swapped

    tree.write(tree.root / "views" / "dashboard" / "index.html", b"written")

    assert (resolved / "dashboard" / "index.html").read_bytes() == b"written"
    assert (outside / "dashboard" / "index.html").read_bytes() == b"outside"
    assert entries(outside) == {"dashboard", "dashboard/index.html"}
