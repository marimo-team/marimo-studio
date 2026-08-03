"""Compose workspace validation with Marimo runtime inspection."""

from __future__ import annotations

from marimo_studio._workspace.checks import check_studio as _check_studio
from marimo_studio._workspace.models import StudioConfig
from marimo_studio._workspace.runtime_checks import run_runtime_checks
from marimo_studio.inspect import inspect_notebook
from marimo_studio.types import CheckResult


def check_studio(
    studio: StudioConfig,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Validate the notebook, bindings, templates, and packaged runtime."""
    return _check_studio(
        studio,
        inspect_notebook=inspect_notebook,
        view_name=view_name,
    )


async def check_runtime_studio(
    studio: StudioConfig,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Execute the notebook and verify selected view cells and values."""
    from marimo_studio._compat.runtime_probe import probe_runtime

    return await run_runtime_checks(
        studio,
        inspect_notebook=inspect_notebook,
        view_name=view_name,
        probe_runtime=probe_runtime,
    )


__all__ = ["check_runtime_studio", "check_studio"]
