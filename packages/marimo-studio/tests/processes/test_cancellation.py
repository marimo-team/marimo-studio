"""Protect the core owner that arbitrates provider cancellation and commits."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from marimo_studio._processes.cancellation import (
    ProviderOperationControl,
    current_provider_cancellation,
    current_provider_operation,
    provider_cancellation,
)
from marimo_studio.view_providers import ProviderCancellation


def test_cancellation_prevents_a_later_commit() -> None:
    control = ProviderOperationControl()
    committed = False

    def commit() -> None:
        nonlocal committed
        committed = True

    control.cancellation.cancel()

    assert not control.commit_if_active(commit)
    assert not committed


def test_provider_cancellation_context_does_not_claim_commit_ownership() -> None:
    cancellation = ProviderCancellation()

    with provider_cancellation(cancellation):
        assert current_provider_cancellation() is cancellation
        assert current_provider_operation() is None


def test_active_commit_finishes_before_provider_cancellation() -> None:
    control = ProviderOperationControl()
    commit_started = Event()
    release_commit = Event()
    cancel_started = Event()
    transitions: list[str] = []
    unregister = control.cancellation.register(lambda: transitions.append("cancelled"))

    def commit() -> None:
        transitions.append("commit-started")
        commit_started.set()
        if not release_commit.wait(timeout=2):
            raise RuntimeError("commit was not released")
        transitions.append("commit-finished")

    def cancel() -> None:
        cancel_started.set()
        control.cancellation.cancel()
        transitions.append("cancel-finished")

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            committing = executor.submit(control.commit_if_active, commit)
            assert commit_started.wait(timeout=2)
            cancelling = executor.submit(cancel)
            assert cancel_started.wait(timeout=2)
            release_commit.set()
            assert committing.result(timeout=2)
            cancelling.result(timeout=2)
        assert transitions == [
            "commit-started",
            "commit-finished",
            "cancelled",
            "cancel-finished",
        ]
    finally:
        unregister()
