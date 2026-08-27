---
title: NGA collection explorer
description: Run one National Gallery of Art notebook through vanilla, React, and Svelte views.
---

# NGA collection explorer

`examples/nga.py` loads National Gallery of Art Open Data, joins artwork and
artist records with Polars, and traces a spike in public-domain drawings to the
Index of American Design. Native cell names give each Studio view symbolic
access to the same notebook graph.

Install the repository dependencies and open the notebook in Studio:

```console
make setup
uv run --with polars --with pyobservablejs marimo edit examples/nga.py
```

The first run downloads about 48 MB of compressed inputs from the example's
pinned NGA Open Data revision. Later runs reuse the files from
`$XDG_CACHE_HOME/marimo-studio/nga` or `~/.cache/marimo-studio/nga`.

## Explore three views

| View         | Authoring option | Source                                           | Experience                                                                         |
| ------------ | ---------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------- |
| **Overview** | Vanilla HTML     | One HTML document with inline CSS and JavaScript | Read collection measures, plots, and a native rich-output table                    |
| **Gallery**  | React            | React TSX, CSS, and Deno configuration           | Filter 72 artwork cards and switch the projected chart in place                    |
| **Story**    | Svelte           | Svelte, TypeScript, CSS, and Vite configuration  | Follow an Index of American Design narrative with dynamic metric and chapter loops |

Use the view menu or the navigation inside each page to move among Overview,
Gallery, and Story. The selected runtime and notebook session stay attached as
the presentation changes.

Run the default Overview view as an application:

```console
uv run --with polars --with pyobservablejs marimo run examples/nga.py
```

## Inspect the project contract

Each view directory contains `view.toml` and authored source. Gallery and Story
also contain their React or Svelte build configuration and dependency locks.
Generated `.artifacts/` directories are ignored. The example check copies the
project to a temporary directory and builds every view from source.

Inspect the Svelte source catalog and mounts from the repository root:

```console
uv run marimo-studio view inspect story \
  --target examples/nga.py \
  --format json
```

Build a production artifact for the Overview view:

```console
uv run marimo-studio view build overview \
  --target examples/nga.py \
  --profile production
```

The Source workspace reads the ordered document catalog returned by the
selected provider. It exposes the Vanilla HTML document, React components,
Svelte components, configuration, and read-only dependency locks through one
scrollable tab strip.

## Follow dynamic projections

The React Gallery view selects one named chart at runtime:

```tsx
const activeChart = CHARTS[chartIndex];

return <marimo-cell name={activeChart.name} data-marimo-allow="*" />;
```

The Svelte Story view mounts value and cell projections from iterable records:

```svelte
{#each metrics as metric}
  <strong mo-value={metric.selector}></strong>
{/each}

{#each chapters as chapter}
  <marimo-cell name={chapter.name} data-marimo-allow="*"></marimo-cell>
{/each}
```

Studio records each mount declaration during the build. When a host mounts or
its target changes, Studio resolves the target against the current notebook.

Continue with [Choose an authoring option](../guide/authoring-options.md) for
starters or [Notebook result mounts](../reference/projections.md) for targets,
wildcard authorization, and lifecycle behavior.
