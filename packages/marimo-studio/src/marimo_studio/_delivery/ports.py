"""Static export configuration and adapter contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from marimo_studio._delivery.browser_ports import BrowserRuntimeProjector


@dataclass(frozen=True)
class StaticRuntimeConfig:
    user: Mapping[str, object]
    overrides: Mapping[str, object]


class StaticRuntimeConfigLoader(Protocol):
    def __call__(self, notebook: Path) -> StaticRuntimeConfig: ...


@dataclass(frozen=True)
class ExportAdapters:
    browser: BrowserRuntimeProjector
    runtime_config: StaticRuntimeConfigLoader
