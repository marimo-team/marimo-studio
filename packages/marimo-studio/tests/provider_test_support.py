"""Shared fixtures for provider boundary tests."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import EntryPoint
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

import marimo_studio._views.create as workspace_setup_module
import marimo_studio.view_providers._host as providers_module
from marimo_studio._artifacts.inputs import project_input_paths
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers import (
    BuildProfile,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterCellTarget,
    StarterContext,
    StarterPlan,
    ViewProject,
)
from marimo_studio.view_providers._bundled.vanilla import provider as vanilla_provider
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
    provider_key,
)


def provider_starter_context(
    root: Path,
    *,
    view_name: str = "dashboard",
    notebook_name: str = "analysis",
) -> StarterContext:
    """Return a complete starter context from a saved test notebook."""
    from marimo_studio import inspect_notebook
    from marimo_studio._views.starter_context import starter_context

    from .helpers import notebook_source

    notebook = root / f"{notebook_name}.py"
    if not notebook.is_file():
        notebook.write_text(
            notebook_source(root / "cell-executed"),
            encoding="utf-8",
        )
    return starter_context(
        inspect_notebook(notebook, include_code=True),
        None,
        view_name,
    )


def provider_build_request(
    project: ViewProject,
    inspection: ProjectInspection,
    staging_root: Path,
    *,
    profile: BuildProfile = "development",
    cache_root: Path | None = None,
    revision: str = "sha256:test",
    command_timeout: float = 120.0,
) -> BuildRequest:
    cancellation = ProviderCancellation()
    return BuildRequest(
        project=project,
        inspection=inspection,
        inputs=project_input_paths(project, inspection),
        project_revision=revision,
        profile=profile,
        staging_root=staging_root,
        cache_root=cache_root or artifact_root(project) / ".cache",
        cancellation=cancellation,
        runner=create_provider_runner(project, cancellation, command_timeout),
        command_timeout=command_timeout,
    )


class EntryPointStub:
    def __init__(self, provider: object, module: str | None = None) -> None:
        self._provider = provider
        self.module = module or provider.__class__.__module__

    def load(self) -> object:
        return self._provider


class ProviderStub:
    def __init__(
        self,
        provider_id: str,
        starter_key: str,
        *,
        available: bool = True,
        profiles: tuple[BuildProfile, ...] = ("development", "production"),
    ) -> None:
        del profiles
        self.provider_key = provider_id.replace(":", "/", 1)
        self.info: ProviderInfo = vanilla_provider.info
        self.starter = ProviderStarter(
            key=starter_key.rsplit(":", 1)[-1].rsplit("/", 1)[-1],
            title="Test starter",
            summary="Creates one HTML document.",
            documents=(PurePosixPath("index.html"),),
        )
        self.available = available
        self.availability_error: Exception | None = None
        self.starters_error: Exception | None = None
        self.create_error: Exception | None = None
        self.inspection_error: Exception | None = None
        self.plan: Mapping[PurePosixPath, bytes] | None = None
        self.plan_cell_targets: tuple[StarterCellTarget, ...] = ()
        self.inspection: ProjectInspection | None = None
        self.report: BuildResult | None = None
        self.build_calls = 0
        self.plan_calls = 0
        self.starter_calls = 0

    def availability(
        self,
        project: ViewProject | None = None,
    ) -> ProviderAvailability:
        del project
        if self.availability_error is not None:
            raise self.availability_error
        if self.available:
            return ProviderAvailability(True)
        return ProviderAvailability(
            False,
            reason="The provider executable is missing.",
            action="Install the provider executable.",
        )

    def starters(self) -> tuple[ProviderStarter, ...]:
        self.starter_calls += 1
        if self.starters_error is not None:
            raise self.starters_error
        return (self.starter,)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        del starter, context
        self.plan_calls += 1
        if self.create_error is not None:
            raise self.create_error
        return StarterPlan(
            files=self.plan
            or {PurePosixPath("index.html"): b"<!doctype html><html></html>"},
            cell_targets=self.plan_cell_targets,
        )

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        del request
        if self.inspection_error is not None:
            raise self.inspection_error
        return self.inspection or inspection()

    def build(self, request: BuildRequest) -> BuildResult:
        self.build_calls += 1
        if self.report is not None:
            return self.report
        document = request.staging_root / "index.html"
        document.write_text("<!doctype html><html></html>", encoding="utf-8")
        return BuildResult(PurePosixPath("index.html"), ())


def candidate(
    name: str,
    provider: object,
    *,
    distribution: str | None = None,
    module: str | None = None,
) -> ProviderCandidate:
    package = distribution or f"test-{name}"
    if hasattr(provider, "provider_key"):
        cast(Any, provider).provider_key = provider_key(package, name)
    return ProviderCandidate(
        registration=name,
        distribution=package,
        version="1.0.0",
        entry_point=cast(EntryPoint, EntryPointStub(provider, module)),
    )


def inspection() -> ProjectInspection:
    return ProjectInspection(
        editor_documents=(SourceDocument(PurePosixPath("index.html"), "html", "edit"),),
        input_scope=(
            ProjectInput(PurePosixPath("index.html"), "file"),
            ProjectInput(PurePosixPath("view.toml"), "file"),
        ),
        mounts=(),
        diagnostics=(),
        build_fingerprint="test-provider-v1",
    )


def inspect_provider(provider: Any, project: ViewProject) -> ProjectInspection:
    return cast(ProjectInspection, provider.inspect(inspection_request(project)))


def project(root: Path, provider: ProviderStub) -> ViewProject:
    return ViewProject(
        name="dashboard",
        root=root,
        manifest=root / "view.toml",
        provider=provider.provider_key,
        options={"entrypoint": "index.html"},
    )


def cache_root(root: Path) -> Path:
    cache = root.parent / f"{root.name}-live" / ".artifacts" / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache.resolve()


def install_registry(
    monkeypatch: pytest.MonkeyPatch,
    registry: ProviderRegistry,
) -> None:
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)
    monkeypatch.setattr(workspace_setup_module, "provider_registry", lambda: registry)
