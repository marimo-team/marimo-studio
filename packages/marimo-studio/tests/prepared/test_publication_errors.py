from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from marimo_export.repository import RepositoryBusyError

from marimo_studio._prepared.errors import publication_error


def test_a_busy_export_cache_is_a_transient_retry() -> None:
    error = publication_error(
        RepositoryBusyError("The export repository maintenance lock remained busy."),
        None,
        cast(Any, SimpleNamespace(sites=())),
    )

    assert error.code == "repository_busy"
    assert error.transient is True
    assert error.public_hint
