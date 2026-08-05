"""Build starter source files from a notebook cell inventory."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path

from marimo_studio._cell_refs import cell_ref_candidates
from marimo_studio.types import CellRef, CellSpec

_STARTER_CSS = """\
/* THEME */

:root {
  color-scheme: light dark;
  --monospace-font: ui-monospace, "SFMono-Regular", Consolas, monospace;
  --text-font: "PT Sans", ui-sans-serif, system-ui, sans-serif;
  --heading-font: var(--text-font);
  --background: light-dark(#ffffff, #111713);
  --foreground: light-dark(#17201b, #edf3ef);
  --card: light-dark(#f8faf9, #18201b);
  --card-foreground: var(--foreground);
  --muted: light-dark(#f0f4f2, #202923);
  --muted-foreground: light-dark(#64716a, #a9b5ae);
  --popover: light-dark(#ffffff, #18201b);
  --popover-foreground: var(--foreground);
  --border: light-dark(#dce3df, #344039);
  --input: light-dark(#c8d2cc, #435048);
  --primary: light-dark(#0877d1, #3ba7ad);
  --primary-foreground: light-dark(#ffffff, #111713);
  --secondary: light-dark(#f0f4f2, #edf3ef);
  --secondary-foreground: light-dark(#17201b, #18201b);
  --accent: light-dark(#edf7ff, #173d3e);
  --accent-foreground: light-dark(#075fa8, #c4efeb);
  --destructive: light-dark(#c62f2f, #f87171);
  --destructive-foreground: light-dark(#ffffff, #111713);
  --ring: var(--primary);
  --link: light-dark(#075fa8, #7fc4ff);
  --radius: 8px;
}

body {
  margin: 0;
  background: var(--background);
  color: var(--foreground);
  font-family: var(--text-font);
}

marimo-cell {
  --marimo-cell-font: var(--text-font);
  --marimo-cell-heading-font: var(--heading-font);
  --marimo-cell-monospace-font: var(--monospace-font);
  --marimo-cell-background: transparent;
  --marimo-cell-foreground: var(--foreground);
  --marimo-cell-surface: var(--card);
  --marimo-cell-muted: var(--muted);
  --marimo-cell-muted-foreground: var(--muted-foreground);
  --marimo-cell-border-color: var(--border);
  --marimo-cell-accent: var(--primary);
  --marimo-cell-accent-foreground: var(--primary-foreground);
  --marimo-cell-radius: var(--radius);
}

/* APP */

.view-header h1 {
  text-wrap: balance;
}

marimo-cell {
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
    <link rel="stylesheet" href="app.css">
  </head>
  <body>
    <main id="app-shell" class="studio-view">
      <header class="view-header mb-8">
        <p class="studio-eyebrow mb-2">{notebook_title}</p>
        <h1
          class="m-0 font-heading text-4xl font-semibold tracking-tight"
        >
          {view_title}
        </h1>
      </header>
      <section class="flex flex-col gap-6" aria-label="Notebook cells">
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
