"""Build starter source files from a notebook cell inventory."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path

from marimo_studio._cell_refs import cell_ref_candidates
from marimo_studio.types import CellRef, CellSpec

_STARTER_CSS = """\
:root {
  color-scheme: light dark;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: Canvas;
  color: CanvasText;
}

.studio-view {
  width: min(100% - 2rem, 72rem);
  margin-inline: auto;
  padding-block: clamp(2rem, 5vw, 4rem);
}

.view-header {
  margin-block-end: 2rem;
}

.view-header p {
  margin: 0 0 0.35rem;
  color: color-mix(in srgb, CanvasText 62%, transparent);
  font-size: 0.75rem;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.view-header h1 {
  margin: 0;
  font-size: clamp(1.75rem, 4vw, 2.75rem);
  letter-spacing: -0.035em;
}

.notebook-cells {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

marimo-cell {
  display: block;
  min-width: 0;
}
"""


def _title(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").strip().title()


def _starter_template(
    name: str,
    notebook_name: str,
    aliases: tuple[str, ...],
) -> str:
    title = escape(f"{_title(notebook_name)} · {_title(name)}")
    notebook_title = escape(_title(notebook_name))
    view_title = escape(_title(name))
    cells = "\n".join(
        f'        <marimo-cell name="{escape(alias, quote=True)}"></marimo-cell>'
        for alias in aliases
    )
    if cells:
        cells += "\n"
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="./_marimo-studio/views/{name}/static/app.css">
  </head>
  <body>
    <main id="app-shell" class="studio-view">
      <header class="view-header">
        <p>{notebook_title}</p>
        <h1>{view_title}</h1>
      </header>
      <section class="notebook-cells" aria-label="Notebook cells">
{cells}      </section>
    </main>
  </body>
</html>
"""


def starter_view_files(
    view_root: Path,
    name: str,
    notebook_name: str,
    aliases: tuple[str, ...],
) -> dict[Path, str]:
    """Return the source files for a new view."""
    root = view_root / name
    return {
        root / "index.html": _starter_template(name, notebook_name, aliases),
        root / "app.css": _STARTER_CSS,
    }


def starter_aliases(
    cells: tuple[CellSpec, ...],
    configured: Mapping[str, CellRef],
) -> tuple[tuple[str, ...], dict[str, CellRef]]:
    """Return ordered projection names and bindings for anonymous cells."""
    native_names = {cell.name for cell in cells if cell.name is not None}
    existing: dict[int, str] = {}
    candidates = tuple((cell.ref, cell) for cell in cells)
    for alias, ref in configured.items():
        if alias in native_names:
            continue
        matches = cell_ref_candidates(ref, candidates)
        if len(matches) == 1 and matches[0].name is None:
            existing.setdefault(matches[0].index, alias)

    used = set(native_names) | set(configured)
    aliases: list[str] = []
    bindings: dict[str, CellRef] = {}
    for cell in cells:
        if cell.name is not None:
            aliases.append(cell.name)
            continue
        alias = existing.get(cell.index)
        if alias is None:
            base = f"cell-{cell.index + 1}"
            alias = base
            suffix = 2
            while alias in used:
                alias = f"{base}-{suffix}"
                suffix += 1
            bindings[alias] = cell.ref
            used.add(alias)
        aliases.append(alias)
    return tuple(aliases), bindings
