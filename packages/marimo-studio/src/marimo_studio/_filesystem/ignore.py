"""Keep a Studio-owned generated directory out of version control.

A ``.gitignore`` that matches every name, itself included, makes Git skip the
directory without changes to the repository's own ignore rules. Python tools
mark their caches and virtual environments the same way.
"""

from __future__ import annotations

from pathlib import Path

from marimo_studio._filesystem.files import ABSENT, ConditionalWriteError, FileTree

IGNORE_FILE = ".gitignore"
_IGNORE_ALL = b"# marimo Studio generates this directory.\n*\n"


def ignore_generated_directory(tree: FileTree, directory: Path) -> None:
    """Add an ignore-everything ``.gitignore`` to ``directory`` when it has none."""
    path = directory / IGNORE_FILE
    if tree.stat(path) is not None:
        return
    try:
        tree.write(path, _IGNORE_ALL, expect=ABSENT, mode=0o644)
    except ConditionalWriteError:
        return
