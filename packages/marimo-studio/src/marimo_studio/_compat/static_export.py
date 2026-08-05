"""Read Marimo configuration for a serverless browser runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._compat.version import assert_supported_version


@dataclass(frozen=True)
class StaticRuntimeConfig:
    user: Mapping[str, object]
    overrides: Mapping[str, object]


def static_runtime_config(notebook: Path) -> StaticRuntimeConfig:
    """Resolve the user and project settings active for ``notebook``."""
    assert_supported_version()
    from marimo._config.manager import get_default_config_manager

    manager = get_default_config_manager(current_path=str(notebook))
    return StaticRuntimeConfig(
        user=manager.get_user_config(),
        overrides=manager.get_config_overrides(),
    )


__all__ = ["StaticRuntimeConfig", "static_runtime_config"]
