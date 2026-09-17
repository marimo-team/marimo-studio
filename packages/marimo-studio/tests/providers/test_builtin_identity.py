"""Validate built-in provider catalog and Vanilla projection identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers._bundled.vanilla import provider as vanilla_provider
from marimo_studio.view_providers._host import provider_registry

from ..deno_provider_test_support import project as _project

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


def test_vanilla_mount_declaration_identity_survives_unrelated_layout_edits(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, vanilla_provider, "marimo-studio/vanilla")
    source = root / "index.html"
    source.write_text(
        """<!doctype html>
<html lang="en">
  <head><title>View</title></head>
  <body>
    <main id="app-shell">
      <marimo-output value="summary"></marimo-output>
      <marimo-output value="rich_table"></marimo-output>
      <marimo-output value="rich_table"></marimo-output>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )
    before = vanilla_provider.inspect(inspection_request(project)).mounts

    source.write_text(
        source.read_text(encoding="utf-8").replace(
            '      <marimo-output value="summary"></marimo-output>\n',
            "      <p>Updated layout</p>\n",
        ),
        encoding="utf-8",
    )
    after = vanilla_provider.inspect(inspection_request(project)).mounts

    assert [site.id for site in before if site.allowed_targets == ("rich_table",)] == [
        site.id for site in after
    ]
    assert len({site.id for site in after}) == 2
