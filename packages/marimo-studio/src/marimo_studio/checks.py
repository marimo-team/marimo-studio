"""Compose workspace validation with Marimo runtime inspection."""

from __future__ import annotations

from importlib.metadata import version

from marimo_studio._composition import (
    create_browser_runtime_projector,
    create_tooling_adapters,
    marimo_release_identity,
)
from marimo_studio._runtime_limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._workspace.checks import check_studio as _check_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.runtime_checks import run_runtime_checks
from marimo_studio.errors import MarimoStudioError
from marimo_studio.inspect import inspect_notebook
from marimo_studio.types import CheckResult


def _compatibility_details(*, passed: bool) -> dict[str, object]:
    required = marimo_release_identity()
    return {
        "validation": "pass" if passed else "fail",
        "studio": {"version": version("marimo-studio")},
        "requiredRelease": required,
        "marimo": required.copy() if passed else None,
        "browser": required.copy() if passed else None,
        "adapterFamily": "private",
    }


def _compatibility_check() -> CheckResult:
    try:
        browser = create_browser_runtime_projector()
    except MarimoStudioError as error:
        return CheckResult(
            "compatibility",
            "fail",
            str(error),
            code=error.code,
            details=_compatibility_details(passed=False),
        )
    return CheckResult(
        "compatibility",
        "pass",
        f"Validated Marimo {browser.version} and its packaged browser runtime",
        details=_compatibility_details(passed=True),
    )


def check_studio(
    studio: StudioWorkspace,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Validate the notebook, bindings, templates, and packaged runtime."""
    compatibility = _compatibility_check()
    if compatibility.status == "fail":
        return (compatibility,)
    return (
        *_check_studio(
            studio,
            inspect_notebook=inspect_notebook,
            view_name=view_name,
        ),
        compatibility,
    )


async def check_runtime_studio(
    studio: StudioWorkspace,
    *,
    view_name: str | None = None,
    timeout: float = DEFAULT_RUNTIME_TIMEOUT,
) -> tuple[CheckResult, ...]:
    """Execute the notebook and verify selected view cells and values."""
    return await run_runtime_checks(
        studio,
        inspect_notebook=inspect_notebook,
        view_name=view_name,
        probe_runtime=create_tooling_adapters().runner,
        timeout=timeout,
    )


__all__ = ["check_runtime_studio", "check_studio"]
