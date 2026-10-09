"""Protect concurrent Deno catalog probes from cancelled availability state."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, cast

import pytest

import marimo_studio._views.catalog as catalog_module
import marimo_studio.view_providers._host as providers_module
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._processes.supervisor import ProcessResult
from marimo_studio.view_providers import _toolkit as toolkit
from marimo_studio.view_providers._builtin._deno import runtime as deno_runtime
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import ProviderStub, candidate


def test_cancelled_concurrent_deno_catalog_probe_retries_successfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "deno"
    binary.write_bytes(b"deno")
    binary.chmod(0o755)
    providers = (
        ProviderStub("example/react", "react"),
        ProviderStub("example/svelte", "svelte"),
    )
    for provider in providers:
        cast(Any, provider).availability = deno_runtime.deno_availability
    monkeypatch.setattr(
        providers_module,
        "_REGISTRY",
        ProviderRegistry(
            tuple(candidate(provider.starter.key, provider) for provider in providers)
        ),
    )
    monkeypatch.setattr(deno_runtime, "deno_binary", lambda: str(binary))

    lock = threading.Lock()
    cancelled_probes_started = threading.Event()
    cancelled_barrier = threading.Barrier(
        len(providers),
        action=cancelled_probes_started.set,
    )
    retry_barrier = threading.Barrier(len(providers))
    calls = 0

    class Supervisor:
        def __init__(self) -> None:
            self.cancelled = threading.Event()

        def cancel(self) -> None:
            self.cancelled.set()

        def run(
            self,
            _command: list[str],
            _timeout: float,
            **_kwargs: object,
        ) -> ProcessResult:
            nonlocal calls
            with lock:
                calls += 1
                attempt = calls
            if attempt <= len(providers):
                cancelled_barrier.wait(timeout=2)
                if not self.cancelled.wait(timeout=2):
                    raise AssertionError("Cancelled Deno probe was not stopped")
                return ProcessResult(1, b"", b"")
            retry_barrier.wait(timeout=2)
            return ProcessResult(0, b"deno 2.9.5\n", b"")

    monkeypatch.setattr(toolkit, "ProcessSupervisor", Supervisor)

    async def cancel_catalog() -> None:
        inventory = asyncio.create_task(run_provider_operation(catalog_module.starters))
        started = await asyncio.to_thread(cancelled_probes_started.wait, 2)
        inventory.cancel()
        with pytest.raises(asyncio.CancelledError):
            await inventory
        assert started

    asyncio.run(cancel_catalog())
    inventory = catalog_module.starters()

    assert [starter.availability.available for starter in inventory] == [True, True]
    assert calls == 4
