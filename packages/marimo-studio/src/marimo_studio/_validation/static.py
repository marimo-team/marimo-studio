"""Compose workspace validation with Marimo runtime inspection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path

from marimo_studio._composition import (
    create_browser_runtime_projector,
    create_worker_runtime_probe,
    marimo_release_identity,
)
from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.results import CheckResult
from marimo_studio._validation.runtime import run_runtime_checks
from marimo_studio._validation.static_rules import check_studio as _check_studio
from marimo_studio._views.inspection import inspect_view_mounts
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError
from marimo_studio.view_providers import MountDeclaration


@dataclass(frozen=True)
class CheckReport:
    """Static and optional runtime checks for a Studio workspace."""

    notebook: Path
    view: str | None
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return not any(result.status == "fail" for result in self.checks)

    def extend(self, checks: tuple[CheckResult, ...]) -> CheckReport:
        return replace(self, checks=(*self.checks, *checks))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "ok": self.ok,
            "notebook": str(self.notebook),
            "view": self.view,
            "checks": [result.to_dict() for result in self.checks],
        }


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
    _published_mounts: Mapping[str, tuple[MountDeclaration, ...]] | None = None,
) -> CheckReport:
    """Validate the notebook, view projects, projections, and packaged runtime."""
    compatibility = _compatibility_check()
    if compatibility.status == "fail":
        return CheckReport(studio.notebook, view_name, (compatibility,))
    return CheckReport(
        notebook=studio.notebook,
        view=view_name,
        checks=(
            *_check_studio(
                studio,
                inspect_notebook=inspect_notebook,
                inspect_mounts=inspect_view_mounts,
                view_name=view_name,
                published_mounts=_published_mounts,
            ),
            compatibility,
        ),
    )


async def check_runtime_studio(
    studio: StudioWorkspace,
    *,
    view_name: str | None = None,
    timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    _published_mounts: Mapping[str, tuple[MountDeclaration, ...]] | None = None,
) -> tuple[CheckResult, ...]:
    """Execute the complete notebook and verify selected projected results."""
    return await run_runtime_checks(
        studio,
        inspect_notebook=inspect_notebook,
        view_name=view_name,
        probe_runtime=create_worker_runtime_probe(),
        timeout=timeout,
        published_mounts=_published_mounts,
    )
