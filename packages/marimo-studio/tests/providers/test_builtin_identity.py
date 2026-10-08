"""Validate built-in provider catalog and Vanilla projection identity."""

from __future__ import annotations

import pytest

from marimo_studio.view_providers._host import provider_registry

pytestmark = pytest.mark.supported_python


def test_built_in_registration_labels_resolve_canonical_provider_ids() -> None:
    registry = provider_registry()
    diagnostics = tuple(
        item for item in registry.diagnostics() if item.distribution == "marimo-studio"
    )

    assert {item.registration: item.provider_key for item in diagnostics} == {
        "notebook-kit": "marimo-studio/notebook-kit",
        "react": "marimo-studio/react",
        "svelte": "marimo-studio/svelte",
        "vanilla": "marimo-studio/vanilla",
    }
    assert {
        provider.key: provider.requirement
        for provider, _starter in registry.starter_records()
        if provider.distribution == "marimo-studio"
    } == {
        "marimo-studio/notebook-kit": "marimo-studio[deno]",
        "marimo-studio/react": "marimo-studio[deno]",
        "marimo-studio/svelte": "marimo-studio[deno]",
        "marimo-studio/vanilla": "marimo-studio",
    }
