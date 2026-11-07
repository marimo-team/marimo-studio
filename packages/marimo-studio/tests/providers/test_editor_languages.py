"""Keep the editor languages Studio reports in the list Source loads."""

from __future__ import annotations

import json
from importlib.metadata import entry_points
from pathlib import Path

from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_DOCUMENT
from marimo_studio.view_providers._builtin import (
    deno_obsnotebook,
    deno_react,
    deno_svelte,
    quarto,
)
from marimo_studio.view_providers._builtin.latex import LATEX
from marimo_studio.view_providers._builtin.typst import TYPST
from marimo_studio.view_providers._host import conformance
from marimo_studio.view_providers._host.registry import ENTRY_POINT_GROUP

# Source's language test loads every language in this fixture.
_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "protocol"
    / "fixtures"
    / "source-languages.json"
)


def test_source_lists_every_language_a_builtin_provider_reports() -> None:
    reported = {
        "latex": set(LATEX.languages.values()),
        "notebook-kit": set(deno_obsnotebook._PROJECT.editor_languages.values()),
        "quarto": set(quarto._LANGUAGES.values()),
        "react": set(deno_react._PROJECT.editor_languages.values()),
        "svelte": set(deno_svelte._PROJECT.editor_languages.values()),
        "typst": set(TYPST.languages.values()),
        # The entry document and the stylesheets and scripts it links.
        "vanilla": {"html", "css", "javascript"},
    }
    builtin = {
        point.name
        for point in entry_points(group=ENTRY_POINT_GROUP)
        if point.dist is not None and point.dist.name == "marimo-studio"
    }
    # View configuration, provider guidance, and diagnostic source files.
    studio = {
        VIEW_MANIFEST_DOCUMENT.language,
        "markdown",
        "plaintext",
        *conformance._SOURCE_LANGUAGES.values(),
    }

    assert set(reported) == builtin
    assert (
        sorted(studio.union(*reported.values()))
        == json.loads(_FIXTURE.read_text(encoding="utf-8"))["languages"]
    )
