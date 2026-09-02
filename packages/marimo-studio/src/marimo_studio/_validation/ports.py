from __future__ import annotations

from typing import Protocol

from marimo_studio._processes.limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio._validation.results import CheckResult
from marimo_studio._workspace.models import StudioWorkspace


class RuntimeChecker(Protocol):
    """Validate one saved workspace through a contained runtime owner."""

    async def __call__(
        self,
        studio: StudioWorkspace,
        *,
        view_name: str | None = None,
        expected_revisions: dict[str, str] | None = None,
        timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    ) -> tuple[CheckResult, ...]: ...
