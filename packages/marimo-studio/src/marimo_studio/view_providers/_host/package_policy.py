"""Built-in provider requirements selected by package composition."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

BUILTIN_PROVIDER_DISTRIBUTION: Final = "marimo-studio"
VANILLA_PROVIDER_ID: Final = "marimo-studio/vanilla"

BUILTIN_PROVIDER_REQUIREMENTS: Final = MappingProxyType(
    {
        "marimo-studio/latex": "marimo-studio",
        "marimo-studio/notebook-kit": "marimo-studio[deno]",
        "marimo-studio/quarto": "marimo-studio",
        "marimo-studio/react": "marimo-studio[deno]",
        "marimo-studio/svelte": "marimo-studio[deno]",
        "marimo-studio/typst": "marimo-studio[typst]",
        VANILLA_PROVIDER_ID: "marimo-studio",
    }
)
DEFAULT_STARTER_ID: Final = f"{VANILLA_PROVIDER_ID}:default"
