"""Bundled provider requirements selected by package composition."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

BUNDLED_PROVIDER_DISTRIBUTION: Final = "marimo-studio"
VANILLA_PROVIDER_ID: Final = "marimo-studio/vanilla"

BUNDLED_PROVIDER_REQUIREMENTS: Final = MappingProxyType(
    {
        "marimo-studio/react": "marimo-studio[deno]",
        "marimo-studio/svelte": "marimo-studio[deno]",
        VANILLA_PROVIDER_ID: "marimo-studio",
    }
)
DEFAULT_STARTER_ID: Final = f"{VANILLA_PROVIDER_ID}:default"
