from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._filesystem.files import FileTree


@pytest.fixture
def tree(tmp_path: Path) -> FileTree:
    root = tmp_path / "workspace"
    root.mkdir()
    return FileTree(root)


@pytest.fixture
def shaped_tree(filesystem_shape: str, tree: FileTree) -> FileTree:
    """Return a tree on each filesystem shape Studio supports."""
    return tree


def entries(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}
