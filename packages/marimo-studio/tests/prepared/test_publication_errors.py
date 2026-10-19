from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from marimo_export.errors import TransportError
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


def test_a_managed_server_start_failure_names_the_preparation_timeout() -> None:
    start = TransportError(
        "the managed marimo server did not become ready", code="server_start_failed"
    )

    exported = publication_error(
        start, None, cast(Any, SimpleNamespace(sites=())), prepare_timeout=0.5
    )

    assert exported.code == "server_start_failed"
    assert "allows 0.5 seconds" in exported.public_hint
    assert "--prepare-timeout" in exported.public_hint
    assert "prepare_timeout" in exported.public_hint


def test_a_lost_export_server_does_not_blame_the_preparation_timeout() -> None:
    lost = TransportError("the managed marimo server closed", code="transport_closed")

    exported = publication_error(
        lost, None, cast(Any, SimpleNamespace(sites=())), prepare_timeout=30
    )

    assert "--prepare-timeout" not in exported.public_hint
    assert "marimo run" in exported.public_hint
