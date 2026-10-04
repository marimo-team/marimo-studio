"""Coordinate Studio's notebook writes with Marimo's own notebook saves."""

from __future__ import annotations

from collections.abc import Collection
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from marimo_studio._composition import create_notebook_write_lock


def notebook_write_lock(
    notebook: Path,
    writes: Collection[Path],
) -> AbstractContextManager[None]:
    """Return Marimo's notebook lock when ``writes`` rewrites ``notebook``.

    Marimo holds this lock from its header read through its write, so a
    transaction under it cannot interleave with a notebook save. Studio takes
    it inside the workspace catalog lock. A Marimo save holds it without
    waiting for a Studio lock, so this order cannot deadlock.
    """
    if notebook not in writes:
        return nullcontext()
    return create_notebook_write_lock()(notebook)
