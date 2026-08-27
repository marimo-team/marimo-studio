"""Workspace-level authoring operations shared by public adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from marimo_studio._notebook.inspection import (
    inspect_notebook_result,
    inspect_runtime,
)
from marimo_studio._notebook.records import CellSelector, InspectionResult
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._processes.provider_operation import run_provider_operation
from marimo_studio._views.api import bind_cell as bind_cell_operation
from marimo_studio._views.api import create_view as create_view_operation
from marimo_studio._views.catalog import starters as installed_starters
from marimo_studio._views.overview import overview
from marimo_studio._views.records import Starter, StudioOverview, ViewSetupResult
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.models import BindingResult
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.registry import ProviderDiagnostic


@dataclass(frozen=True)
class ProviderReport:
    """Describe installed provider registrations and their availability."""

    providers: tuple[ProviderDiagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "providers": [provider.to_dict() for provider in self.providers],
        }


async def status(notebook: Path) -> StudioOverview:
    """Return configuration and view state for one notebook."""
    return await run_provider_operation(partial(overview, notebook))


async def inspect_notebook(
    notebook: Path,
    *,
    runtime: bool = False,
    include_code: bool = False,
    selectors: tuple[CellSelector, ...] = (),
    output_expressions: bool = False,
    limit: int | None = None,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
) -> InspectionResult:
    """Return selected saved cells with optional isolated runtime evidence."""
    if runtime:
        return await inspect_runtime(
            notebook,
            include_code=include_code,
            selectors=selectors,
            output_expressions=output_expressions,
            limit=limit,
            runtime_timeout=runtime_timeout,
        )
    return await asyncio.to_thread(
        inspect_notebook_result,
        notebook,
        include_code=include_code,
        selectors=selectors,
        output_expressions=output_expressions,
        limit=limit,
    )


async def starters() -> tuple[Starter, ...]:
    """Return installed view starters and their availability."""
    return await run_provider_operation(installed_starters)


async def create_view(
    notebook: Path,
    name: str,
    *,
    starter: str | Starter | None = None,
    dry_run: bool = False,
) -> ViewSetupResult:
    """Create one view and reject an existing name."""
    return await run_provider_operation(
        partial(
            create_view_operation,
            notebook,
            name,
            starter=starter,
            dry_run=dry_run,
        )
    )


async def bind_cell(
    notebook: Path,
    alias: str,
    cell_selector: CellSelector,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Bind an alias to one saved notebook cell."""

    def operation() -> BindingResult:
        return bind_cell_operation(
            load_studio(notebook),
            alias,
            cell_selector,
            dry_run=dry_run,
            overwrite=overwrite,
        )

    return await run_provider_operation(operation)


async def diagnose_providers(provider: str | None = None) -> ProviderReport:
    """Return finalized provider diagnostics, optionally for one key."""
    records = await run_provider_operation(provider_registry().diagnostics)
    selected = tuple(
        record
        for record in records
        if provider is None or record.provider_key == provider
    )
    if provider is not None and not selected:
        raise ConfigurationError(f"Unknown view provider {provider!r}")
    return ProviderReport(selected)
