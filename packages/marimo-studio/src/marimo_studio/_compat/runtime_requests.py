"""Construct private Marimo runtime requests behind one stable function."""

from __future__ import annotations

from typing import Any


def instantiate_notebook_request(*, auto_run: bool) -> Any:
    """Return the request model from the pinned Marimo release."""
    from marimo._session.requests import InstantiateNotebookRequest

    return InstantiateNotebookRequest(
        object_ids=[],
        values=[],
        auto_run=auto_run,
    )
