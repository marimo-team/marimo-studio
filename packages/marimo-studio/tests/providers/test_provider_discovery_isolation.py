"""Protect isolated provider discovery, metadata, and catalog probes."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from marimo_studio._processes.cancellation import provider_cancellation
from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    ProviderAvailability,
    ProviderCancellation,
    StarterContext,
)
from marimo_studio.view_providers._host.operations.process import (
    ProviderOperationCancelled,
)
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..provider_test_support import inspection
from .test_process_isolation import (
    _kill_survivors,
    _project,
    _registry,
    _wait_until_dead,
    catalog_provider,
)

pytestmark = pytest.mark.native_process

_PROVIDER_MODULE = "tests.providers.test_process_isolation"
_PROCESS_START_TIMEOUT = 15.0
_METADATA_OPERATION_TIMEOUT = 1.5 if os.name == "nt" else 0.25
_METADATA_ELAPSED_LIMIT = 3.0 if os.name == "nt" else 0.8
_CONTAINMENT_ELAPSED_LIMIT = 5.0 if os.name == "nt" else 3.0


def _candidate(
    registration: str,
    provider: str,
    *,
    distribution: str = "test-discovery",
) -> ProviderCandidate:
    return ProviderCandidate(
        registration=registration,
        distribution=distribution,
        version="1.0.0",
        entry_point=EntryPoint(
            name=registration,
            value=f"{_PROVIDER_MODULE}:{provider}",
            group="marimo_studio.view_provider",
        ),
    )


def test_provider_python_work_does_not_consume_the_command_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    installed = _registry("delayed", "delayed_provider").get("test-process/delayed")
    project = _project(tmp_path, installed.key, delay=0.3, command=0.2)

    result = installed.inspect(inspection_request(project, command_timeout=0.4))

    assert result.build_fingerprint == inspection().build_fingerprint


def test_external_catalog_and_starter_creation_stay_out_of_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    import_marker = tmp_path / "imports"
    catalog_marker = tmp_path / "catalog"
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_IMPORT_MARKER", str(import_marker))
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_CATALOG_MARKER", str(catalog_marker))
    registry = _registry("catalog", "catalog_provider")
    installed = registry.get("test-process/catalog")

    availability = installed.availability()
    starters = installed.starters()
    files = installed.create(starters[0], StarterContext("report", "analysis"))

    assert availability == ProviderAvailability(True)
    assert files == catalog_provider.plan
    operations = [
        line.split(":", 1)
        for line in catalog_marker.read_text(encoding="utf-8").splitlines()
    ]
    assert [operation for operation, _pid in operations] == [
        "availability",
        "starters",
        "create",
    ]
    worker_pids = tuple(
        int(line) for line in import_marker.read_text(encoding="utf-8").splitlines()
    )
    assert len(worker_pids) == 4
    assert os.getpid() not in worker_pids
    assert all(int(pid) != os.getpid() for _operation, pid in operations)
    _wait_until_dead(worker_pids)


def test_cancelled_initial_discovery_retries_without_a_partial_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    marker = tmp_path / "discovery-pids"
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_IMPORT_MARKER", str(marker))
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_BLOCK", "describe")
    candidates = tuple(
        _candidate(name, "catalog_provider", distribution="test-retry")
        for name in ("first", "second")
    )
    registry = ProviderRegistry(candidates, isolate_operations=True)
    control = ProviderCancellation()
    results: list[tuple[str, ...]] = []
    errors: list[BaseException] = []

    def discover() -> None:
        with provider_cancellation(control):
            try:
                results.append(registry.ids)
            except BaseException as error:
                errors.append(error)

    worker = threading.Thread(target=discover)
    worker.start()
    pids: tuple[int, ...] = ()
    try:
        deadline = time.monotonic() + _PROCESS_START_TIMEOUT
        while time.monotonic() < deadline:
            if marker.is_file():
                pids = tuple(
                    int(line)
                    for line in marker.read_text(encoding="utf-8").splitlines()
                )
                if len(pids) == 2:
                    break
            threading.Event().wait(0.01)
        assert len(pids) == 2

        control.cancel()
        worker.join(timeout=_PROCESS_START_TIMEOUT)

        assert not worker.is_alive()
        assert results == []
        assert len(errors) == 1
        assert isinstance(errors[0], ProviderOperationCancelled)
        _wait_until_dead(pids)

        monkeypatch.delenv("MARIMO_STUDIO_PROVIDER_BLOCK")
        assert registry.ids == ("test-retry/first", "test-retry/second")
        assert all(diagnostic.loaded for diagnostic in registry.diagnostics())
        _wait_until_dead(
            tuple(int(line) for line in marker.read_text(encoding="utf-8").splitlines())
        )
    finally:
        control.cancel()
        worker.join(timeout=_PROCESS_START_TIMEOUT)
        if marker.is_file():
            _kill_survivors(
                tuple(
                    int(line)
                    for line in marker.read_text(encoding="utf-8").splitlines()
                )
            )


def test_external_descriptions_run_concurrently_in_candidate_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    barrier = tmp_path / "description-barrier"
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_DISCOVERY_BARRIER", str(barrier))
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_DISCOVERY_DELAY", "0.25")
    registry = ProviderRegistry(
        tuple(
            _candidate(name, "catalog_provider", distribution="test-parallel")
            for name in ("second", "first")
        ),
        isolate_operations=True,
        extension_timeout=1.5,
    )

    started = time.monotonic()
    ids = registry.ids
    elapsed = time.monotonic() - started
    monkeypatch.delenv("MARIMO_STUDIO_PROVIDER_DISCOVERY_BARRIER")
    monkeypatch.delenv("MARIMO_STUDIO_PROVIDER_DISCOVERY_DELAY")

    assert ids == ("test-parallel/first", "test-parallel/second")
    assert len(barrier.read_text(encoding="utf-8").splitlines()) == 2
    assert elapsed < 1.2
    assert [item.registration for item in registry.diagnostics()] == [
        "second",
        "first",
    ]


def test_timed_out_description_keeps_a_healthy_provider_usable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    marker = tmp_path / "blocked-description-pid"
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_DESCRIPTION_MARKER", str(marker))
    registry = ProviderRegistry(
        (
            _candidate(
                "blocked",
                "blocking_description_provider",
                distribution="test-timeout",
            ),
            _candidate("healthy", "catalog_provider", distribution="test-timeout"),
        ),
        isolate_operations=True,
        extension_timeout=_METADATA_OPERATION_TIMEOUT,
    )
    blocked_pid = 0

    try:
        started = time.monotonic()
        ids = registry.ids
        elapsed = time.monotonic() - started

        assert ids == ("test-timeout/healthy",)
        assert elapsed < _METADATA_ELAPSED_LIMIT
        blocked_pid = int(marker.read_text(encoding="utf-8"))
        _wait_until_dead((blocked_pid,))
        diagnostics = registry.diagnostics()
        assert [item.registration for item in diagnostics] == ["blocked", "healthy"]
        assert "exceeded" in (diagnostics[0].error or "")
        assert diagnostics[1].loaded
    finally:
        if blocked_pid:
            _kill_survivors((blocked_pid,))


@pytest.mark.parametrize("operation", ("starters", "availability"))
def test_cancelled_parallel_catalog_probes_drain_every_provider_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    import marimo_studio._views.catalog as catalog_module
    import marimo_studio.view_providers._host as providers_module
    from marimo_studio._processes.provider_operation import run_provider_operation

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    marker = tmp_path / f"{operation}-pids"
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_CATALOG_MARKER", str(marker))
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_BLOCK", operation)
    candidates = tuple(
        ProviderCandidate(
            registration=name,
            distribution="test-parallel",
            version="1.0.0",
            entry_point=EntryPoint(
                name=name,
                value=f"{_PROVIDER_MODULE}:catalog_provider",
                group="marimo_studio.view_provider",
            ),
        )
        for name in ("first", "second")
    )
    registry = ProviderRegistry(candidates, isolate_operations=True)
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)
    pids: tuple[int, ...] = ()

    async def exercise() -> tuple[int, ...]:
        inventory = asyncio.create_task(run_provider_operation(catalog_module.starters))
        deadline = asyncio.get_running_loop().time() + _PROCESS_START_TIMEOUT
        selected: tuple[int, ...] = ()
        while asyncio.get_running_loop().time() < deadline:
            if marker.is_file():
                selected = tuple(
                    int(line.split(":", 1)[1])
                    for line in marker.read_text(encoding="utf-8").splitlines()
                    if line.startswith(f"{operation}:")
                )
                if len(selected) == 2:
                    break
            await asyncio.sleep(0.01)
        assert len(selected) == 2
        inventory.cancel()
        results = await asyncio.gather(inventory, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        await asyncio.to_thread(_wait_until_dead, selected)
        return selected

    try:
        pids = asyncio.run(exercise())
    finally:
        _kill_survivors(pids)


@pytest.mark.parametrize(
    "operation",
    ("describe", "availability", "starters", "create"),
)
def test_external_provider_metadata_operations_have_a_containment_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_BLOCK", operation)
    registry = _registry(
        "catalog",
        "catalog_provider",
        timeout=_METADATA_OPERATION_TIMEOUT,
    )
    started = time.monotonic()

    if operation == "describe":
        assert registry.ids == ()
        error = registry.diagnostics()[0].error or ""
    else:
        installed = registry.get("test-process/catalog")
        if operation == "availability":
            result = installed.availability()
            error = result.reason or ""
        elif operation == "starters":
            assert installed.starters() == ()
            error = registry.diagnostics()[0].error or ""
        else:
            with pytest.raises(ConfigurationError) as captured:
                installed.create(
                    catalog_provider.starter,
                    StarterContext("report", "analysis"),
                )
            error = str(captured.value)

    assert time.monotonic() - started < _CONTAINMENT_ELAPSED_LIMIT
    assert "exceeded" in error
