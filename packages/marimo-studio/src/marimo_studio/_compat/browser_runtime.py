"""Build browser runtime projections for the pinned Marimo release."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from marimo_studio._capabilities import BrowserRuntimeProjection
from marimo_studio._compat.browser_notebook import (
    browser_notebook_source,
    selector_specs,
)
from marimo_studio.types import ValueReference


def _digest(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class PrivateBrowserRuntimeProjector:
    """Build one browser runtime projection for the pinned Marimo release."""

    def __init__(self, *, version: str, commit: str) -> None:
        self.version = version
        self.commit = commit

    def project(
        self,
        notebook: Path,
        source: str,
        *,
        values: Mapping[str, ValueReference],
        outputs: Mapping[str, ValueReference],
    ) -> BrowserRuntimeProjection:
        code = browser_notebook_source(
            notebook,
            source,
            values,
            outputs,
        )
        identity_code = browser_notebook_source(notebook, source, {}, {})
        return BrowserRuntimeProjection(
            instance=_digest(self.version, self.commit, identity_code),
            version=self.version,
            commit=self.commit,
            code=code,
            value_specs=selector_specs(values),
            output_specs=selector_specs(outputs),
        )


__all__ = ["PrivateBrowserRuntimeProjector"]
