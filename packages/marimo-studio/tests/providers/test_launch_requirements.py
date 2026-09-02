from __future__ import annotations

from typing import Any, cast

import pytest

from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)
from marimo_studio.view_providers._host.requirements import (
    resolve_launch_requirements,
)

from ..provider_test_support import (
    EntryPointStub,
    ProviderStub,
    candidate,
    install_registry,
)


def _versioned_candidate(name: str, version: str) -> ProviderCandidate:
    provider = ProviderStub(f"example-suite/{name}", "default")
    return ProviderCandidate(
        registration=name,
        distribution="example-suite",
        version=version,
        entry_point=cast(Any, EntryPointStub(provider)),
    )


def test_launch_requirements_reject_an_invalid_provider_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example-suite/report", "default")
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (candidate("report", provider, distribution="example-suite"),),
            {"example-suite/report": "not a requirement ???"},
        ),
    )

    with pytest.raises(ConfigurationError, match="invalid Python requirement"):
        resolve_launch_requirements(("example-suite/report",))


def test_launch_requirements_reject_a_distribution_name_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example-suite/report", "default")
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (candidate("report", provider, distribution="example-suite"),),
            {"example-suite/report": "wrong-package==1.0.0"},
        ),
    )

    with pytest.raises(ConfigurationError, match="requirement names"):
        resolve_launch_requirements(("example-suite/report",))


def test_launch_requirements_reject_conflicting_installed_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (
                _versioned_candidate("report", "1.0.0"),
                _versioned_candidate("web", "2.0.0"),
            ),
            {
                "example-suite/report": "example-suite",
                "example-suite/web": "example-suite",
            },
        ),
    )

    with pytest.raises(ConfigurationError, match="conflicting installed versions"):
        resolve_launch_requirements(("example-suite/report", "example-suite/web"))


def test_launch_requirements_reject_an_invalid_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (_versioned_candidate("report", "not-a-version"),),
            {"example-suite/report": "example-suite"},
        ),
    )

    with pytest.raises(ConfigurationError, match="invalid distribution version"):
        resolve_launch_requirements(("example-suite/report",))
