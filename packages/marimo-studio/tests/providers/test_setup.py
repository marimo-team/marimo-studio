"""Protect starter creation at the workspace transaction boundary."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._views.api import prepare_view
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import BuildResult, ProjectDiagnostic
from marimo_studio.view_providers._host.identity import starter_id
from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_REQUIREMENTS,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import ProviderStub, candidate, install_registry


def _install(
    monkeypatch: pytest.MonkeyPatch,
    provider: ProviderStub,
    *,
    name: str = "custom",
) -> str:
    registry = ProviderRegistry((candidate(name, provider),))
    install_registry(monkeypatch, registry)
    return starter_id(registry.ids[0], provider.starter.key)


def _dependencies(notebook: Path) -> tuple[str, ...]:
    document = read_notebook_metadata(notebook)
    assert document is not None
    return tuple(document["dependencies"])


@pytest.mark.parametrize("dry_run", (False, True))
def test_unavailable_starter_rejects_setup_before_any_write(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    provider = ProviderStub("example/unavailable", "custom", available=False)
    starter = _install(monkeypatch, provider)
    original = notebook_path.read_bytes()

    with pytest.raises(ConfigurationError, match="unavailable"):
        prepare_view(notebook_path, starter=starter, dry_run=dry_run)

    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_starter_failure_rejects_setup_before_any_write(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example/broken", "custom")
    provider.create_error = RuntimeError("could not render starter")
    starter = _install(monkeypatch, provider)
    original = notebook_path.read_bytes()

    with pytest.raises(ConfigurationError, match="could not render starter"):
        prepare_view(notebook_path, starter=starter)

    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_invalid_starter_paths_reject_setup_before_any_write(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example/invalid", "custom")
    provider.plan = {PurePosixPath(".artifacts/output"): b"generated"}
    starter = _install(monkeypatch, provider)
    original = notebook_path.read_bytes()

    with pytest.raises(ConfigurationError, match=r"reserves|overlapping|colliding"):
        prepare_view(notebook_path, starter=starter)

    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_creation_does_not_inspect_or_build_the_authored_project(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example/repairable", "custom")
    provider.report = BuildResult(
        None,
        (
            ProjectDiagnostic(
                "build-input-invalid",
                "error",
                "Fix the authored source.",
            ),
        ),
    )
    provider.inspection_error = RuntimeError("inspection must be explicit")
    starter = _install(monkeypatch, provider)

    result = prepare_view(notebook_path, starter=starter)

    assert result.root.joinpath("view.toml").is_file()
    assert result.root.joinpath("index.html").is_file()
    assert result.to_dict()["schema"] == 2
    assert provider.build_calls == 0


def test_repeated_setup_and_vanilla_preserve_the_react_requirement(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    react = ProviderStub("marimo-studio/react", "react")
    vanilla = ProviderStub("marimo-studio/vanilla", "vanilla")
    registry = ProviderRegistry(
        (
            candidate("react", react, distribution="marimo-studio"),
            candidate("vanilla", vanilla, distribution="marimo-studio"),
        ),
        BUNDLED_PROVIDER_REQUIREMENTS,
    )
    install_registry(monkeypatch, registry)

    prepare_view(notebook_path, "dashboard", starter="marimo-studio/react:react")
    prepare_view(notebook_path)
    prepare_view(notebook_path, "report", starter="marimo-studio/vanilla:vanilla")

    dependencies = _dependencies(notebook_path)
    assert dependencies.count("marimo-studio[deno]") == 1
    assert "marimo-studio" not in dependencies


def test_setup_keeps_requirements_for_every_installed_third_party_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ProviderStub("example-suite/first", "first")
    second = ProviderStub("example-suite/second", "second")
    other = ProviderStub("other-suite/report", "report")
    registry = ProviderRegistry(
        (
            candidate("first", first, distribution="example-suite"),
            candidate("second", second, distribution="example-suite"),
            candidate("report", other, distribution="other-suite"),
        )
    )
    install_registry(monkeypatch, registry)

    prepare_view(notebook_path, "dashboard", starter="example-suite/first:first")
    prepare_view(notebook_path, "detail", starter="example-suite/second:second")
    prepare_view(notebook_path, "report", starter="other-suite/report:report")

    dependencies = _dependencies(notebook_path)
    assert dependencies.count("example-suite==1.0.0") == 1
    assert dependencies.count("other-suite==1.0.0") == 1
