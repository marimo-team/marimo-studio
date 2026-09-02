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
)
from marimo_studio.view_providers._host.operations.process import (
    ProviderOperationCancelled,
)
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..provider_test_support import inspection, provider_starter_context
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
_METADATA_OPERATION_TIMEOUT = 1.5
_CONCURRENT_DISCOVERY_TIMEOUT = _PROCESS_START_TIMEOUT + 5.0


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


def _import_pids(marker: Path) -> tuple[int, ...]:
    if not marker.is_dir():
        return ()
    return tuple(int(item.name.split("-", 1)[0]) for item in marker.iterdir())


def _catalog_operations(marker: Path) -> tuple[tuple[str, int], ...]:
    if not marker.is_dir():
        return ()
    operations: list[tuple[str, int]] = []
    for item in marker.iterdir():
        operation, pid, _nonce = item.name.split("-", 2)
        operations.append((operation, int(pid)))
    return tuple(operations)


def test_provider_python_work_does_not_consume_the_command_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    installed = _registry("delayed", "delayed_provider").get("test-process/delayed")
    project = _project(tmp_path, installed.key, delay=2.1, command=0.0)

    result = installed.inspect(inspection_request(project, command_timeout=2.0))

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
    plan = installed.create(
        starters[0],
        provider_starter_context(tmp_path, view_name="report"),
    )

    assert availability == ProviderAvailability(True)
    assert plan.files == catalog_provider.plan
    operations = _catalog_operations(catalog_marker)
    assert sorted(operation for operation, _pid in operations) == [
        "availability",
        "create",
        "starters",
    ]
    worker_pids = _import_pids(import_marker)
    assert len(worker_pids) == 4
    assert os.getpid() not in worker_pids
    assert all(pid != os.getpid() for _operation, pid in operations)
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
            if marker.is_dir():
                pids = _import_pids(marker)
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
        _wait_until_dead(_import_pids(marker))
    finally:
        control.cancel()
        worker.join(timeout=_PROCESS_START_TIMEOUT)
        if marker.is_dir():
            _kill_survivors(_import_pids(marker))


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
        extension_timeout=_CONCURRENT_DISCOVERY_TIMEOUT,
    )

    ids = registry.ids
    monkeypatch.delenv("MARIMO_STUDIO_PROVIDER_DISCOVERY_BARRIER")
    monkeypatch.delenv("MARIMO_STUDIO_PROVIDER_DISCOVERY_DELAY")

    assert ids == ("test-parallel/first", "test-parallel/second")
    assert len(set(_import_pids(barrier))) == 2
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
        ids = registry.ids

        assert ids == ("test-timeout/healthy",)
        blocked_pid = int(marker.read_text(encoding="utf-8"))
        _wait_until_dead((blocked_pid,))
        diagnostics = registry.diagnostics()
        assert [item.registration for item in diagnostics] == ["blocked", "healthy"]
        assert f"exceeded its {_METADATA_OPERATION_TIMEOUT:g} second limit" in (
            diagnostics[0].error or ""
        )
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
            selected = tuple(
                sorted(
                    {
                        pid
                        for recorded_operation, pid in _catalog_operations(marker)
                        if recorded_operation == operation
                    }
                )
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
        recorded = tuple(
            pid
            for recorded_operation, pid in _catalog_operations(marker)
            if recorded_operation == operation
        )
        _kill_survivors(tuple(set((*pids, *recorded))))


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
                    provider_starter_context(tmp_path, view_name="report"),
                )
            error = str(captured.value)

    assert f"exceeded its {_METADATA_OPERATION_TIMEOUT:g} second limit" in error
