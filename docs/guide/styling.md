---
title: Style a view
description: Use authored CSS, scoped utility classes, theme tokens, and projection variables in a Studio view.
---

# Style a view

Start with authored CSS in the view project. Studio also generates scoped
utility styles for classes under `#app-shell`, including the classes used by
the bundled starters.

```html
<main id="app-shell" class="studio-view">
  <p class="studio-eyebrow">Quarterly review</p>
  <section class="studio-card p-6">
    <marimo-output value="revenue_chart"></marimo-output>
  </section>
</main>
```

The built-in shortcuts are:

| Class            | Purpose                                   |
| ---------------- | ----------------------------------------- |
| `studio-view`    | Responsive centered page container        |
| `studio-card`    | Card surface with theme border and colors |
| `studio-button`  | Accessible button treatment               |
| `studio-eyebrow` | Small uppercase section label             |

`studio-view` sets a maximum width and page padding. Use a plain
`<div id="app-shell"></div>` when the component defines its own page layout.

[Wind4](https://unocss.dev/presets/wind4) utility classes, a compact convention
for composing CSS from class names, include `grid`, `gap-6`, `p-6`, `text-sm`,
and `lg:grid-cols-3`. They use the same scoped generator. Studio observes class
changes inside `#app-shell` and refreshes the generated CSS for dynamic
content.

::: warning Browser support
View utilities require the CSS
[`@scope`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@scope)
rule, which limits selectors to a chosen part of the document. In a browser
without that feature, authored CSS and notebook outputs remain available while
Studio reports a style diagnostic.
:::

## Use theme variables

The starter styles read the presentation theme through variables such as:

```css
body {
  margin: 0;
  background: var(--background);
  color: var(--foreground);
  font-family: var(--text-font);
}

.summary {
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--card-foreground);
}
```

Utilities also use `--primary`, `--accent`, `--muted`, `--ring`,
`--heading-font`, `--monospace-font`, and `--radius`. Define project-owned CSS
variables beside these tokens when the view needs a distinct visual system.

## Style projected cells and output

Studio treats native Marimo output subtrees as their own rendering boundary.
Set projection variables on `marimo-cell` or `marimo-output` to integrate that
content with the page:

```css
.report-output {
  --marimo-cell-font: var(--text-font);
  --marimo-cell-heading-font: var(--heading-font);
  --marimo-cell-background: transparent;
  --marimo-cell-foreground: var(--foreground);
  --marimo-cell-surface: var(--card);
  --marimo-cell-border-color: var(--border);
  --marimo-cell-accent: var(--primary);
  --marimo-cell-radius: 0.5rem;
  --marimo-cell-padding: 1rem;
}
```

```html
<marimo-output class="report-output" value="revenue_chart"></marimo-output>
```

Use `--marimo-cell-content-width` for rendered Markdown and
`--marimo-cell-error` for cell error treatment.

## Control loading states

Projection hosts expose `data-state` while they connect, load, update, or fail.
Studio supplies a default skeleton. Adjust its size when the final result has a
known footprint:

```css
marimo-output[value="revenue_chart"] {
  --marimo-cell-skeleton-height: 24rem;
  --marimo-cell-skeleton-radius: 0.5rem;
}

[mo-value="metrics.total"] {
  --marimo-value-skeleton-width: 4ch;
  --marimo-value-skeleton-height: 0.8em;
}
```

Set `data-skeleton="none"` on a cell or output host when an empty loading slot
is the intended layout.

## Add icons

Use an [Iconify](https://iconify.design/docs/iconify-icon/) custom element,
which renders an icon selected by collection and name, inside `#app-shell`:

```html
<button class="studio-button" type="button">
  <iconify-icon icon="lucide:download" aria-hidden="true"></iconify-icon>
  Export
</button>
```

Studio loads the Iconify element when it finds an `iconify-icon`. Icon data can
require network access, so allow the chosen icon source in the hosting content
security policy or package the icon locally.

Check the page in Preview at desktop and narrow widths. Use [Manage view
source](manage-source.md) for project-owned CSS files and [Place notebook
results in a view](notebook-results.md) for projection state and events.
