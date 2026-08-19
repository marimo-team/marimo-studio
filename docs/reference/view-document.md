---
title: View document API
description: Cell, rich-output, and value projections with browser events, readiness, styles, loading states, and relative assets.
---

# View document API

A view is a complete HTML document with one `#app-shell`. Studio injects its
runtime beside that shell and connects every projection to the selected Marimo
runtime.

## Document contract

```html [index.html]
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Revenue dashboard</title>
    <link rel="stylesheet" href="app.css" />
  </head>
  <body>
    <main id="app-shell" class="studio-view">
      <marimo-cell name="summary"></marimo-cell>
      <marimo-output value="report.table"></marimo-output>
      <strong mo-value="report.total"></strong>
    </main>
  </body>
</html>
```

The document must contain one `<head>`, one `<body>`, and one `#app-shell`.
Place every `<marimo-cell>`, `<marimo-output>`, and `mo-value` host inside the
shell.

## `<marimo-cell>` <Badge type="info" text="Complete cell" />

```html
<marimo-cell name="summary"></marimo-cell>
```

`name` accepts a native Marimo cell name or a configured alias. Each name can
appear once per view.

The host uses these `data-state` values:

```text
connecting | loading | stale | ready | missing | error
```

During a reactive rerun, retained output stays visible while the state is
`stale`. An unresolved cell records:

- `data-marimo-diagnostic-code`
- `data-marimo-diagnostic-message`
- `data-marimo-diagnostic-hint`

The host records rendered MIME information in `data-output-mime` and
`data-output-mimes`.

Cell events:

- `marimo-cell-ready`
- `marimo-cell-updated`
- `marimo-cell-error`

## Value references

`<marimo-output value="...">` and `mo-value="..."` accept the same value
reference grammar:

```text
selector  := identifier (dot-key | item)*
dot-key   := "." identifier
item      := "[" non-negative-integer "]"
           | "[" JSON-string "]"
```

Dot selection checks a mapping key, then Python attribute access. Bracket
selection uses item lookup. The root variable must have one defining notebook
cell.

## `<marimo-output>` <Badge type="tip" text="Python object" />

```html
<marimo-output value="df"></marimo-output>
<marimo-output value="report.figure"></marimo-output>
<marimo-output value="results[0]"></marimo-output>
```

The element formats the selected Python object through Marimo's output
registry, then renders its MIME output with Marimo's native output area. Use it
for a table, plot, Markdown object, control, or widget that should look and
behave like notebook output. Each output selector can appear once per view.

The defining notebook cell remains the reactive owner. During a rerun, the
current output stays mounted with `data-state="stale"` until the replacement is
ready. Studio releases formatter-created controls, functions, files, and other
native resources when the selector is replaced or removed.

The host uses these `data-state` values:

```text
connecting | loading | stale | ready | error
```

`data-runtime-cell-id` identifies the defining cell. `data-output-mime`
records the rendered MIME type. Diagnostic failures use the same
`data-marimo-diagnostic-*` attributes as cell projections. Each encoded output
and the aggregate response are bounded to 1,000,000 bytes.

Output events:

- `marimo-output-ready` fires after the first output is mounted.
- `marimo-output-updated` fires after a later reactive replacement is mounted.
- `marimo-output-error` fires when the host enters an error state.

Each event bubbles, crosses shadow boundaries, and carries this detail shape:

```ts
interface MarimoOutputEventDetail {
  selector: string;
  cellId?: string;
  mimetype?: string;
  code?: string;
  message?: string;
  hint?: string;
}
```

## `mo-value` <Badge type="info" text="JSON value" />

```html
<span mo-value="report"></span>
<time mo-value="report.updated_at"></time>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

Strings, numbers, and booleans render as text. Objects and arrays render as
compact JSON. JSON `null` renders as empty text while remaining available to
browser code as `null`.

The host uses these `data-state` values:

```text
connecting | loading | stale | ready | error
```

`data-runtime-cell-id` identifies the current defining cell after Studio
resolves the binding. Studio clears the attribute when the binding is
unavailable.

Use `marimo_studio.LENS_TARGET_SELECTOR` when a Lens mount should select every
runtime-bound cell, output, and value host. Compose authored page regions into
that CSS selector in the notebook.

Each value and the aggregate response are bounded to 1,000,000 encoded bytes.

## Browser value API

Every `[mo-value]` host exposes its current JSON snapshot:

```ts
type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

interface MarimoValueHost extends HTMLElement {
  readonly marimoValue: JsonValue | undefined;
}
```

`undefined` means the first value has not arrived or the current selector is
unavailable. The property keeps its cached snapshot while `data-state` is
`loading` or `stale`.

Register the update listener before reading the property:

```js
const source = document.querySelector("#report-data");

source.addEventListener("marimo-value-updated", (event) => {
  render(event.detail.value);
});

if (source.marimoValue !== undefined) {
  render(source.marimoValue);
}
```

### `marimo-value-updated`

```ts
interface MarimoValueUpdatedDetail {
  selector: string;
  value: JsonValue;
}
```

The event fires for the first resolved value and each changed JSON encoding.
Studio sets `marimoValue` and `data-state="ready"` before dispatch. The event
bubbles, crosses shadow boundaries, and is not cancelable.

A reactive rerun that produces the same encoded JSON updates the host state
and skips another event.

### `marimo-value-error`

```ts
interface MarimoValueErrorDetail {
  selector: string;
  code: string;
  message: string;
  hint?: string;
}
```

The event fires once when the host enters an error state. Studio clears
`marimoValue`, sets `data-state="error"`, records the diagnostic attributes,
then dispatches the event. It bubbles and crosses shadow boundaries.

## Browser readiness

```js
await window.marimoStudio.ready();
const diagnostics = window.marimoStudio.diagnostics();
```

`ready()` resolves after every current cell, rich output, and value reaches
`ready` or a terminal diagnostic. It waits through reactive updates and
view-source refreshes while retained content remains visible.

`diagnostics()` returns the current projection, presentation, host, and runtime
failures.

The root `<html>` element publishes combined state in
`data-marimo-studio-state`:

```text
connecting | loading | ready | error
```

`marimo-studio:idle` fires on `document` when current projections settle. Its
detail is `{ state: "ready" | "error" }`.

## Built-in styles

Studio generates scoped Wind4 utilities from the classes inside `#app-shell`.
The generated rules stop before Marimo-owned cell output, so utility classes
style the authored document while Marimo components keep their native styles.

Stable shortcuts:

| Class            | Behavior                                             |
| ---------------- | ---------------------------------------------------- |
| `studio-view`    | Centered `max-w-7xl` page with responsive padding    |
| `studio-card`    | Semantic bordered surface using view theme variables |
| `studio-button`  | Compact bordered control with focus styling          |
| `studio-eyebrow` | Small uppercase label using muted text               |

Semantic utility colors read these variables from `app.css`:

```text
--background             --foreground
--card                   --card-foreground
--muted                  --muted-foreground
--popover                --popover-foreground
--border                 --input
--primary                --primary-foreground
--secondary              --secondary-foreground
--accent                 --accent-foreground
--destructive            --destructive-foreground
--ring                   --link
--text-font              --heading-font
--monospace-font         --radius
```

Generated utilities require native CSS `@scope` support. When a browser lacks
it, Studio reports a style diagnostic while authored CSS and notebook outputs
continue to run.

## Loading and output variables

| Scope           | Properties                                                                                                                               |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Output skeleton | `--marimo-cell-skeleton-height`, `--marimo-cell-skeleton-color`, `--marimo-cell-skeleton-radius`                                         |
| Value skeleton  | `--marimo-value-skeleton-width`, `--marimo-value-skeleton-height`, `--marimo-value-skeleton-color`, `--marimo-value-skeleton-radius`     |
| Cell typography | `--marimo-cell-font`, `--marimo-cell-heading-font`, `--marimo-cell-monospace-font`                                                       |
| Cell surface    | `--marimo-cell-background`, `--marimo-cell-surface`, `--marimo-cell-foreground`, `--marimo-cell-muted`, `--marimo-cell-muted-foreground` |
| Cell frame      | `--marimo-cell-border`, `--marimo-cell-border-color`, `--marimo-cell-radius`, `--marimo-cell-padding`, `--marimo-cell-content-width`     |
| Cell accent     | `--marimo-cell-accent`, `--marimo-cell-accent-foreground`, `--marimo-cell-error`                                                         |

Set `data-skeleton="none"` on a cell or rich output when an empty first-load
region is intentional.

## Relative assets and reserved paths

Reference view files through ordinary relative URLs:

```html
<link rel="stylesheet" href="app.css" />
<script type="module" src="scripts/app.js"></script>
<img src="images/logo.svg" alt="Acme" />
```

Relative imports and CSS `url(...)` references resolve from their source file.
Regular files in the view directory are served with the document and included
in a static export. Keep credentials outside that directory.

The top-level paths `_marimo-studio`, `@file`, `public`, and
`public-files-sw.js` belong to Studio or Marimo. Use other names for authored
asset directories.

Named `iconify-icon` elements fetch their icon data from the Iconify API. Use
inline SVG when a deployment must render without that network request.

## HTMX cell route

HTMX is available as `window.htmx`. Request one configured cell host from the
current view:

```html
<button
  type="button"
  hx-get="./_marimo-studio/views/dashboard/cells/detail_table"
  hx-target="#details"
>
  Show details
</button>
<section id="details" aria-live="polite"></section>
```

Replace `dashboard` and `detail_table` with the current view and cell name.
Studio processes utility classes in the inserted fragment and connects the new
host to the current Marimo runtime.

[Use notebook results](../guide/notebook-results.md) applies the projection
contracts in an authoring workflow. [Use HTML, CSS, and
JavaScript](../guide/web-platform.md) covers modules, browser behavior, assets,
and styling.
