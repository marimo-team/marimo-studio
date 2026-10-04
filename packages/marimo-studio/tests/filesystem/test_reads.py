from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from marimo_studio._filesystem.errors import FileTooLargeError, UnsafePathError
from marimo_studio._filesystem.files import FileTree

from ..helpers import link_directory

pytestmark = pytest.mark.supported_python


def _symlink(target: Path, link: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")


def test_read_returns_content_mode_and_a_version_of_that_content(
    tree: FileTree,
) -> None:
    path = tree.root / "notebook.py"
    path.write_bytes(b"import marimo\n")

    first = tree.read(path, max_bytes=1024)

    assert first.content == b"import marimo\n"
    assert first.mode == path.stat().st_mode & 0o777
    assert first.version == tree.read(path, max_bytes=1024).version
    assert first.version == tree.version(path)

    path.write_bytes(b"import marimo as mo\n")

    assert tree.version(path) != first.version


def test_read_refuses_a_file_over_its_bound(tree: FileTree) -> None:
    path = tree.root / "large.bin"
    path.write_bytes(b"x" * 11)

    with pytest.raises(FileTooLargeError):
        tree.read(path, max_bytes=10)


def test_missing_entries_report_absence(tree: FileTree) -> None:
    missing = tree.root / "missing.txt"

    assert tree.version(missing) is None
    assert tree.stat(missing) is None
    assert not tree.exists(missing)
    with pytest.raises(FileNotFoundError):
        tree.read(missing, max_bytes=1024)


def test_paths_with_parent_segments_are_refused(tree: FileTree) -> None:
    with pytest.raises(UnsafePathError):
        tree.read(tree.root / "nested" / ".." / ".." / "outside.txt", max_bytes=1024)


def test_paths_outside_the_root_are_refused(tree: FileTree, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")

    with pytest.raises(UnsafePathError):
        tree.read(outside, max_bytes=1024)
    with pytest.raises(UnsafePathError):
        tree.write(outside, b"changed")
    assert outside.read_bytes() == b"secret"


def test_reads_and_writes_refuse_a_linked_file(tree: FileTree, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    link = tree.root / "linked.txt"
    _symlink(outside, link)

    with pytest.raises(UnsafePathError):
        tree.read(link, max_bytes=1024)
    with pytest.raises(UnsafePathError):
        tree.write(link, b"changed")
    assert outside.read_bytes() == b"secret"


def test_writes_refuse_a_linked_ancestor(tree: FileTree, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link_directory(outside, tree.root / "views")

    with pytest.raises(UnsafePathError):
        tree.write(tree.root / "views" / "view.toml", b"changed")
    assert not tuple(outside.iterdir())


def test_regular_files_lists_every_file_with_its_size(tree: FileTree) -> None:
    (tree.root / "b").mkdir()
    (tree.root / "b" / "index.html").write_bytes(b"<p>")
    (tree.root / "a.css").write_bytes(b"body{}")

    files = tree.regular_files(tree.root, max_entries=10)

    assert {path.relative_to(tree.root).as_posix(): size for path, size in files} == {
        "a.css": 6,
        "b/index.html": 3,
    }


def test_regular_files_refuses_a_tree_over_its_entry_bound(tree: FileTree) -> None:
    for index in range(3):
        (tree.root / f"{index}.txt").write_bytes(b"x")

    with pytest.raises(UnsafePathError):
        tree.regular_files(tree.root, max_entries=2)


def test_regular_files_refuses_links(tree: FileTree, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link_directory(outside, tree.root / "linked")

    with pytest.raises(UnsafePathError, match="symlink"):
        tree.regular_files(tree.root, max_entries=10)


def test_tree_version_records_links_without_following_them(
    tree: FileTree, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "tool").write_bytes(b"one")
    link_directory(outside, tree.root / "linked")
    before = tree.tree_version(tree.root, max_entries=10)

    (outside / "tool").write_bytes(b"two!")
    (outside / "added").write_bytes(b"x")

    assert tree.tree_version(tree.root, max_entries=10) == before

    tree.remove(tree.root / "linked")
    (tree.root / "linked").mkdir()

    assert tree.tree_version(tree.root, max_entries=10) != before


def test_tree_version_tracks_contents_not_directory_timestamps(
    tree: FileTree,
) -> None:
    nested = tree.root / "assets"
    nested.mkdir()
    (nested / "app.js").write_bytes(b"one")
    before = tree.tree_version(tree.root, max_entries=10)
    later = time.time() + 5
    os.utime(nested, (later, later))

    assert tree.tree_version(tree.root, max_entries=10) == before

    (nested / "app.js").write_bytes(b"two!")

    assert tree.tree_version(tree.root, max_entries=10) != before
