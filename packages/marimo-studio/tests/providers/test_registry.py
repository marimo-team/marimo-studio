"""Protect provider discovery, catalog recovery, and registry boundaries."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import marimo_studio._views.catalog as catalog_module
import marimo_studio.view_providers._host as providers_module
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    ProviderAvailability,
    StarterContext,
    ViewProject,
)
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
    provider_key,
)

from ..provider_test_support import (
    EntryPointStub,
    ProviderStub,
    candidate,
    inspection,
    provider_build_request,
)


def test_catalog_probes_availability_concurrently_and_caches_starters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)
    providers = (
        ProviderStub("example/first", "default"),
        ProviderStub("example/second", "default"),
    )
    availability_calls = {"first": 0, "second": 0}

    def availability(name: str) -> ProviderAvailability:
        availability_calls[name] += 1
        barrier.wait(timeout=1)
        time.sleep(0.15)
        return ProviderAvailability(True)

    cast(Any, providers[0]).availability = lambda _project=None: availability("first")
    cast(Any, providers[1]).availability = lambda _project=None: availability("second")
    registry = ProviderRegistry(
        (
            candidate("first", providers[0]),
            candidate("second", providers[1]),
        )
    )
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)

    started = time.monotonic()
    first = catalog_module.starters()
    elapsed = time.monotonic() - started
    second = catalog_module.starters()

    assert elapsed < 0.8
    assert [starter.provider for starter in first] == [
        "test-first/first",
        "test-second/second",
    ]
    assert second == first
    assert availability_calls == {"first": 2, "second": 2}
    assert [provider.template_calls for provider in providers] == [1, 1]


def test_registry_probes_starters_concurrently_and_caches_successes() -> None:
    barrier = threading.Barrier(2)
    providers = (
        ProviderStub("example/first", "default"),
        ProviderStub("example/second", "default"),
    )
    calls = {"first": 0, "second": 0}

    def starters(name: str, provider: ProviderStub):
        calls[name] += 1
        barrier.wait(timeout=1)
        time.sleep(0.15)
        return (provider.starter,)

    cast(Any, providers[0]).starters = lambda: starters("first", providers[0])
    cast(Any, providers[1]).starters = lambda: starters("second", providers[1])
    registry = ProviderRegistry(
        (
            candidate("first", providers[0]),
            candidate("second", providers[1]),
        )
    )

    started = time.monotonic()
    first = registry.starter_records()
    elapsed = time.monotonic() - started
    second = registry.starter_records()

    assert elapsed < 0.8
    assert [(provider.key, starter.key) for provider, starter in first] == [
        ("test-first/first", "default"),
        ("test-second/second", "default"),
    ]
    assert second == first
    assert calls == {"first": 1, "second": 1}


def test_provider_keys_come_from_distribution_and_registration() -> None:
    assert provider_key("Acme_Views", "report") == "acme-views/report"

    rogue = ProviderStub("marimo-studio/vanilla", "vanilla")
    registry = ProviderRegistry(
        (candidate("vanilla", rogue, distribution="other-package"),)
    )

    assert registry.ids == ("other-package/vanilla",)
    assert "marimo-studio/vanilla" not in registry.ids


def test_async_provider_operations_are_rejected_at_discovery() -> None:
    provider = ProviderStub("example/async", "async")

    async def inspect(_project: ViewProject):
        return provider.inspection

    cast(Any, provider).inspect = inspect
    registry = ProviderRegistry((candidate("async", provider),))

    assert registry.ids == ()
    diagnostic = registry.diagnostics()[0]
    assert diagnostic.provider_key == "test-async/async"
    assert "must be synchronous" in (diagnostic.error or "")


def test_provider_registry_isolates_invalid_candidates() -> None:
    healthy = ProviderStub("example/healthy", "healthy")
    broken = ProviderStub("example/broken", "broken")
    malformed = ProviderStub("example/malformed", "malformed")
    broken.info = replace(
        broken.info,
        api_version=PROVIDER_API_VERSION + 1,
    )
    registry = ProviderRegistry(
        (
            candidate("broken", broken),
            ProviderCandidate(
                registration="INVALID REGISTRATION",
                distribution="broken-package",
                version="1.0.0",
                entry_point=cast(Any, EntryPointStub(malformed)),
            ),
            candidate("healthy", healthy),
        )
    )

    assert registry.ids == ("test-healthy/healthy",)
    diagnostics = {item.registration: item for item in registry.diagnostics()}
    assert diagnostics["healthy"].loaded
    assert diagnostics["broken"].provider_key == "test-broken/broken"
    assert "API version" in (diagnostics["broken"].error or "")
    assert diagnostics["INVALID REGISTRATION"].provider_key is None
    assert "entry-point identity is invalid" in (
        diagnostics["INVALID REGISTRATION"].error or ""
    )


@pytest.mark.parametrize("api_version", (3.0, True))
def test_provider_api_version_requires_an_integer(api_version: object) -> None:
    provider = ProviderStub("example/version", "default")
    provider.info = replace(
        provider.info,
        api_version=cast(Any, api_version),
    )

    registry = ProviderRegistry((candidate("version", provider),))

    assert registry.ids == ()
    assert "API version" in (registry.diagnostics()[0].error or "")


def test_registration_and_starter_keys_are_distribution_scoped() -> None:
    first = ProviderStub("example/first", "report")
    second = ProviderStub("example/second", "report")
    registry = ProviderRegistry(
        (
            candidate("report", first, distribution="first-package"),
            candidate("report", second, distribution="second-package"),
        )
    )

    records = registry.starter_records()
    diagnostics = registry.diagnostics()

    assert [(provider.key, starter.key) for provider, starter in records] == [
        ("first-package/report", "report"),
        ("second-package/report", "report"),
    ]
    assert [item.starters for item in diagnostics] == [
        ("first-package/report:report",),
        ("second-package/report:report",),
    ]
    assert registry.ids == ("first-package/report", "second-package/report")
    assert [item.provider_key for item in diagnostics] == list(registry.ids)
    assert all(item.loaded for item in diagnostics)


def test_provider_options_are_detached_for_each_operation() -> None:
    provider = ProviderStub("example/html", "html")
    registry = ProviderRegistry((candidate("html", provider),))
    key = registry.ids[0]
    root = Path("view")
    project = ViewProject(
        "view",
        root,
        root / "view.toml",
        key,
        {"nested": {"items": ["first"]}},
    )

    first = registry.validate_project(project)
    cast(Any, first.options)["nested"]["items"].append("mutated")
    second = registry.validate_project(project)

    assert project.options == {"nested": {"items": ["first"]}}
    assert second.options == {"nested": {"items": ["first"]}}


@pytest.mark.parametrize(
    ("operation", "message"),
    (
        ("availability", "invalid availability record"),
        ("starters", "requires starters to be a tuple"),
    ),
)
def test_malformed_catalog_results_are_isolated_to_the_provider(
    operation: str,
    message: str,
) -> None:
    provider = ProviderStub("example/catalog", "default")
    if operation == "availability":
        cast(Any, provider).availability = lambda _project=None: object()
    else:
        cast(Any, provider).starters = lambda: [provider.starter]
    registry = ProviderRegistry((candidate("catalog", provider),))
    installed = registry.get(registry.ids[0])

    if operation == "availability":
        assert installed.availability().available is False
    else:
        assert installed.starters() == ()

    diagnostic = registry.diagnostics()[0]
    assert diagnostic.loaded is False
    assert message in (diagnostic.error or "")


@pytest.mark.parametrize("operation", ("availability", "starters"))
def test_provider_catalog_failures_recover_in_the_same_process(
    operation: str,
) -> None:
    provider = ProviderStub("example/recoverable", "default")
    registry = ProviderRegistry((candidate("recoverable", provider),))
    installed = registry.get(registry.ids[0])
    failure = RuntimeError(f"temporary {operation} failure")
    if operation == "availability":
        provider.availability_error = failure
        assert not installed.availability().available
        provider.availability_error = None
        assert installed.availability().available
    else:
        provider.starters_error = failure
        assert registry.starter_records() == ()
        provider.starters_error = None
        assert len(registry.starter_records()) == 1

    diagnostic = registry.diagnostics()[0]
    assert diagnostic.loaded
    assert diagnostic.error is None


@pytest.mark.parametrize("operation", ("availability", "starters"))
def test_provider_catalog_surfaces_process_cleanup_failure(operation: str) -> None:
    provider = ProviderStub("example/cleanup", "default")
    registry = ProviderRegistry((candidate("cleanup", provider),))
    installed = registry.get(registry.ids[0])

    def fail(*_args: object) -> object:
        try:
            raise ProcessCleanupError("catalog process survived")
        except ProcessCleanupError as cleanup:
            raise RuntimeError("catalog failed") from cleanup

    setattr(cast(Any, provider), operation, fail)

    with pytest.raises(ProcessCleanupError, match="catalog process survived"):
        if operation == "availability":
            installed.availability()
        else:
            installed.starters()


@pytest.mark.parametrize("operation", ("create", "inspect", "build"))
def test_provider_project_operations_surface_process_cleanup_failure(
    tmp_path: Path,
    operation: str,
) -> None:
    provider = ProviderStub("example/cleanup", "default")
    registry = ProviderRegistry((candidate("cleanup", provider),))
    installed = registry.get(registry.ids[0])
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {},
    )
    project.manifest.write_text("schema = 1\n", encoding="utf-8")
    project.root.joinpath("index.html").write_text(
        "<!doctype html><html></html>",
        encoding="utf-8",
    )

    def fail(*_args: object) -> object:
        try:
            raise ProcessCleanupError("project process survived")
        except ProcessCleanupError as cleanup:
            raise RuntimeError("project operation failed") from cleanup

    setattr(cast(Any, provider), operation, fail)
    with pytest.raises(ProcessCleanupError, match="project process survived"):
        if operation == "create":
            installed.create(provider.starter, StarterContext("dashboard", "analysis"))
        elif operation == "inspect":
            installed.inspect(inspection_request(project))
        else:
            staging = tmp_path / "staging"
            staging.mkdir()
            installed.build(
                provider_build_request(
                    project,
                    inspection(),
                    staging,
                    cache_root=tmp_path / "cache" / ".artifacts" / ".cache",
                )
            )


def test_manifest_validation_surfaces_provider_process_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import marimo_studio._views.sources as sources_module
    from marimo_studio._workspace.project_manifest import encode_view_manifest

    root = tmp_path / "view"
    root.mkdir()

    def fail_registry() -> object:
        raise ProcessCleanupError("manifest provider process survived")

    monkeypatch.setattr(sources_module, "provider_registry", fail_registry)

    with pytest.raises(
        ProcessCleanupError,
        match="manifest provider process survived",
    ):
        sources_module._validate_view_manifest(
            root,
            "dashboard",
            encode_view_manifest("example/provider"),
            None,
        )


@pytest.mark.parametrize("boundary", ("inspect", "snapshot-inspect", "build"))
def test_public_build_surfaces_provider_process_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    import marimo_studio.view_providers._host as providers_module
    from marimo_studio._views.build import build_view_project_sync
    from marimo_studio._workspace.project_manifest import encode_view_manifest

    provider = ProviderStub("example/cleanup", "default")
    registry = ProviderRegistry((candidate("cleanup", provider),))
    installed = registry.get(registry.ids[0])
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {},
    )
    project.manifest.write_text(
        encode_view_manifest(installed.key),
        encoding="utf-8",
    )
    project.root.joinpath("index.html").write_text(
        "<!doctype html><html></html>",
        encoding="utf-8",
    )

    def fail() -> object:
        try:
            raise ProcessCleanupError("build process survived")
        except ProcessCleanupError as cleanup:
            raise RuntimeError("provider failed") from cleanup

    if boundary == "snapshot-inspect":
        calls = 0

        def inspect_twice(_request: object) -> object:
            nonlocal calls
            calls += 1
            return inspection() if calls == 1 else fail()

        cast(Any, provider).inspect = inspect_twice
    elif boundary == "inspect":
        cast(Any, provider).inspect = lambda _request: fail()
    else:
        cast(Any, provider).build = lambda _request: fail()

    with pytest.raises(ProcessCleanupError, match="build process survived"):
        build_view_project_sync(project)


@pytest.mark.parametrize(
    ("operation", "message"),
    (
        ("inspect", "requires a ProjectInspection record"),
        ("build", "requires a BuildResult record"),
    ),
)
def test_malformed_project_results_fail_at_the_provider_boundary(
    tmp_path: Path,
    operation: str,
    message: str,
) -> None:
    provider = ProviderStub("example/project", "default")
    registry = ProviderRegistry((candidate("project", provider),))
    installed = registry.get(registry.ids[0])
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {},
    )
    project.manifest.write_text("schema = 1\n", encoding="utf-8")
    project.root.joinpath("index.html").write_text(
        "<!doctype html><html></html>",
        encoding="utf-8",
    )
    accepted = inspection()
    with pytest.raises(ConfigurationError, match=message):
        if operation == "inspect":
            cast(Any, provider).inspect = lambda _project: object()
            installed.inspect(inspection_request(project))
        else:
            staging = tmp_path / "staging"
            staging.mkdir()
            cast(Any, provider).build = lambda _request: object()
            request = provider_build_request(
                project,
                accepted,
                staging,
                cache_root=tmp_path / "cache" / ".artifacts" / ".cache",
            )
            installed.build(request)
