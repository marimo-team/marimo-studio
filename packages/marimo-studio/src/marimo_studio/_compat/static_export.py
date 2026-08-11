"""Read Marimo configuration for a serverless browser runtime."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._capabilities import StaticRuntimeConfig


def static_runtime_config(notebook: Path) -> StaticRuntimeConfig:
    """Resolve the user and project settings active for ``notebook``."""
    from marimo._config.manager import get_default_config_manager

    manager = get_default_config_manager(current_path=str(notebook))
    return StaticRuntimeConfig(
        user=manager.get_user_config(),
        overrides=manager.get_config_overrides(),
    )


__all__ = ["StaticRuntimeConfig", "static_runtime_config"]
