"""Run every built-in provider through the public provider check."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from importlib.metadata import EntryPoint, entry_points

import pytest

from marimo_studio.view_providers._host import (
    BUILTIN_PROVIDER_REQUIREMENTS,
    provider_registry,
    selected_registry,
)
from marimo_studio.view_providers._host.registry import (
    ENTRY_POINT_GROUP,
    ProviderCandidate,
    ProviderRegistry,
)
from marimo_studio.view_providers.testing import check_provider

# Selects the test profile that installs each provider's external tool.
_PROFILES = {
    "notebook-kit": pytest.mark.deno,
    "quarto": pytest.mark.quarto,
    "react": pytest.mark.deno,
    "svelte": pytest.mark.deno,
}
_BUILTIN = {
    point.name: point
    for point in entry_points(group=ENTRY_POINT_GROUP)
    if point.dist is not None and point.dist.name == "marimo-studio"
}


@contextmanager
def _separate_distribution(point: EntryPoint) -> Iterator[str]:
    """Load ``point`` from another distribution, in an isolated worker process."""
    candidate = ProviderCandidate(point.name, "acme-split", "1.0.0", point)
    with selected_registry(ProviderRegistry((candidate,), isolate_operations=True)):
        yield candidate.key


def _cases() -> list[object]:
    return [
        pytest.param(
            name,
            placement,
            id=f"{name}-{placement}",
            marks=[
                *([_PROFILES[name]] if name in _PROFILES else []),
                pytest.mark.native_process,
                pytest.mark.xdist_group("builtin-contract"),
            ],
        )
        for name in sorted(_BUILTIN)
        for placement in ("builtin", "separate")
    ]


def test_every_builtin_provider_declares_its_requirement() -> None:
    assert set(BUILTIN_PROVIDER_REQUIREMENTS) == {
        f"marimo-studio/{name}" for name in _BUILTIN
    }


@pytest.mark.parametrize(("name", "placement"), _cases())
def test_builtin_provider_passes_the_provider_check(name: str, placement: str) -> None:
    availability = provider_registry().get(f"marimo-studio/{name}").availability()
    if not availability.available:
        pytest.skip(f"{name} is unavailable: {availability.reason}")
    selected = (
        _separate_distribution(_BUILTIN[name])
        if placement == "separate"
        else nullcontext(f"marimo-studio/{name}")
    )

    with selected as key:
        views = check_provider(key)

    for view in views:
        assert view.published, view.starter
        assert view.warnings == (), view.starter
