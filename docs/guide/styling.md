---
title: Style a view
description: Use authored CSS, theme tokens, and projection variables in a Studio view.
---

# Style a view

The view project owns page layout and visual styling. Add inline styles to a
Vanilla document or import a stylesheet from the selected provider's browser
entry point.

```html
<main id="app-shell" class="report">
  <p class="report-kicker">Quarterly review</p>
  <section class="summary-card">
    <marimo-output value="revenue_chart"></marimo-output>
  </section>
</main>
```

```css
.report,
.report-kicker,
.summary-card {
  box-sizing: border-box;
}

.report {
  width: min(100% - 2rem, 72rem);
  margin-inline: auto;
  padding-block: clamp(2rem, 7vw, 6rem);
}

.report-kicker {
  color: var(--muted-foreground);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.summary-card {
  padding: 1.5rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card);
  color: var(--card-foreground);
}
```

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

The presentation theme also defines `--primary`, `--accent`, `--muted`,
`--ring`, `--heading-font`, `--monospace-font`, and `--radius`. Define
project-owned CSS variables beside these tokens when the view needs a distinct
visual system.

## Use Vanilla browser helpers

The bundled Vanilla starter loads a pinned UnoCSS runtime and the Iconify Icon
web component from jsDelivr. Add utility classes directly to Vanilla HTML:

```html
<section class="grid gap-6 md:grid-cols-2">
  <article class="rounded-lg border border-[var(--border)] p-6">
    <marimo-output value="revenue_chart"></marimo-output>
  </article>
</section>
```

Add a named icon with the registered web component:

```html
<button type="button" class="inline-flex items-center gap-2">
  <iconify-icon inline icon="lucide:download" aria-hidden="true"></iconify-icon>
  Download
</button>
```

These scripts require network access to jsDelivr. Icon data loaded by name also
requires access to the configured Iconify API. Admit those origins in the
hosting content security policy.

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

Check the page in Preview at desktop and narrow widths. Use [Manage view
source](manage-source.md) for project-owned CSS files and [Place notebook
results in a view](notebook-results.md) for projection state and events.
