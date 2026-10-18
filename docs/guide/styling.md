---
title: Style a page
description: Style a view page with your own CSS, theme the notebook cells and outputs it places, and size their loading states.
---

# Style a page

A [page](../reference/glossary.md#page) owns its layout and styling. Write CSS inline in an HTML page, or
import a stylesheet from a React or Svelte entry point. Define page colors and
fonts on `:root`. marimo's theme tokens apply inside placed cells and outputs
and do not reach the rest of the page.

```html
<main id="app-shell" class="report">
  <p class="kicker">Quarterly review</p>
  <section class="card">
    <marimo-output value="revenue_chart"></marimo-output>
  </section>
</main>
```

```css
:root {
  --background: Canvas;
  --foreground: CanvasText;
  --border: color-mix(in srgb, CanvasText 18%, transparent);
  --primary: LinkText;
  --text-font: system-ui, sans-serif;
}

body {
  margin: 0;
  background: var(--background);
  color: var(--foreground);
  font-family: var(--text-font);
}

.report {
  width: min(100% - 2rem, 72rem);
  margin-inline: auto;
  padding-block: clamp(2rem, 7vw, 6rem);
}

.kicker {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.card {
  padding: 1.5rem;
  border: 1px solid var(--border);
  border-radius: 0.5rem;
}
```

Typst, LaTeX, and Quarto documents style themselves with their own templates.
See [Choose a format](formats.md).

## Theme placed cells and outputs

Native marimo output renders inside its own boundary. Set `--marimo-cell-*`
variables on a `marimo-cell` or `marimo-output` host, or on any ancestor, to
match it to the page:

```css
.report {
  --marimo-cell-font: var(--text-font);
  --marimo-cell-background: transparent;
  --marimo-cell-foreground: var(--foreground);
  --marimo-cell-border-color: var(--border);
  --marimo-cell-accent: var(--primary);
  --marimo-cell-radius: 0.5rem;
  --marimo-cell-padding: 1rem;
}
```

| Variable                                                                              | Styles                                                              |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `--marimo-cell-font`, `--marimo-cell-heading-font`                                    | Body and heading fonts                                              |
| `--marimo-cell-foreground`, `--marimo-cell-background`                                | Text and background. Borders and muted text mix from the foreground |
| `--marimo-cell-surface`                                                               | Card and popover surfaces inside the output                         |
| `--marimo-cell-accent`                                                                | Links, selected options, slider fills, and focus rings              |
| `--marimo-cell-border-color`, `--marimo-cell-muted`, `--marimo-cell-muted-foreground` | Borders and muted surfaces and text, set directly                   |
| `--marimo-cell-radius`, `--marimo-cell-padding`                                       | Corner radius and padding                                           |
| `--marimo-cell-content-width`, `--marimo-cell-font-size`                              | Rendered Markdown width and base size                               |
| `--marimo-cell-error`                                                                 | Cell error treatment                                                |

Without an accent, controls use the foreground color and links keep marimo's
link color. Markdown keeps marimo's `1rem` base size. Set
`--marimo-cell-font-size: 1em` to size it from the surrounding element, as the
Reveal.js starter does so notebook text scales with its slides. Tooltips,
dropdown menus, and date pickers open outside the placed cell and keep
marimo's theme.

## Size loading states

`marimo-cell`, `<marimo-output value>`, and `[mo-value]` hosts show a skeleton
while they connect and load. A render host, `<marimo-output render>`, shows the
skeleton until Studio's runtime starts, then shows its progress in its toolbar.
Give a host the size of the final result so the page does not shift:

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

Set `data-skeleton="none"` on a `marimo-cell` or `marimo-output` host to
leave its slot empty while it loads.
Hosts also expose `data-state` for your own loading and error styles.
[Notebook result projections](../reference/projections.md#host-lifecycle)
lists the states.

## Use the HTML starter helpers

The HTML starter loads a pinned [UnoCSS](https://unocss.dev/) runtime and the
[Iconify Icon](https://iconify.design/docs/iconify-icon/) web component from
jsDelivr. Use utility classes and named icons directly in the page:

```html
<section class="grid gap-6 md:grid-cols-2">
  <article class="rounded-lg border border-[var(--border)] p-6">
    <marimo-output value="revenue_chart"></marimo-output>
  </article>
</section>

<button type="button" class="inline-flex items-center gap-2">
  <iconify-icon inline icon="lucide:download" aria-hidden="true"></iconify-icon>
  Download
</button>
```

Both scripts need network access. The hosting Content Security Policy must
allow jsDelivr in `script-src`, the Iconify API in `connect-src`, and the
inline `<style>` element that UnoCSS generates in `style-src`, which usually
means `'unsafe-inline'`. Use precompiled CSS when the host allows only nonce
or hash styles.
