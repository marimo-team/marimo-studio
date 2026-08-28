---
title: One collection, three audience pages
description: Use one National Gallery of Art notebook for a collection brief, artwork browser, and editorial story.
---

# One collection, three audience pages

`examples/nga.py` analyzes National Gallery of Art Open Data once. Three pages
reuse its measures, plots, tables, and controls for different reading tasks.

| Page     | Audience experience                                               | Frontend source   |
| -------- | ----------------------------------------------------------------- | ----------------- |
| Overview | Read collection measures, plots, and a detailed table             | One HTML file     |
| Gallery  | Filter artwork cards and choose the active chart                  | React components  |
| Story    | Follow an editorial narrative with repeated measures and chapters | Svelte components |

## Open the example

```console
make setup
uv run --with polars --with pyobservablejs marimo edit examples/nga.py
```

The first notebook run downloads about 48 MB of compressed input from a pinned
National Gallery of Art Open Data revision. Later runs reuse the cached files.

Choose **Develop**, then use the page menu to move among Overview, Gallery, and
Story. The notebook session stays active while the wording, layout, and
interaction change around its results.

## Compare how the pages use one result

The React Gallery changes the named chart shown in one location:

```tsx
const activeChart = CHARTS[chartIndex];

return <marimo-cell name={activeChart.name} data-marimo-allow="*" />;
```

The Svelte Story repeats notebook measures and complete cells from constant
records:

```svelte
{#each metrics as metric}
  <strong mo-value={metric.selector}></strong>
{/each}

{#each chapters as chapter}
  <marimo-cell name={chapter.name} data-marimo-allow="*"></marimo-cell>
{/each}
```

Studio checks the possible names during the build and resolves the selected
name against the current notebook when the page runs.

## Inspect the source

Open Source to compare the one-file page, React components, and Svelte
components. Each page remains ordinary frontend source beside `examples/nga.py`.

Run the default Overview page as an application:

```console
uv run --with polars --with pyobservablejs marimo run examples/nga.py
```

Continue with [Use HTML, React, or Svelte](../guide/frontend-options.md) or
[Place notebook results on a page](../guide/notebook-results.md).
