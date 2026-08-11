---
title: Work with coding agents
description: Create and activate a Studio view, then repair source, runtime, and rendered browser errors until it is ready to hand off.
---

# Work with coding agents

Marimo Studio gives a coding agent one repair loop for a saved notebook and
its audience-specific views. The agent inspects the notebook graph, creates or
locates a view, selects it in the open workspace, edits ordinary web files,
and analyzes the source, executed notebook, and rendered page.

## Keep notebook and view ownership clear

| Owner               | Content                                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------- |
| Notebook cells      | Computation, analytical context, data access, domain rules, reactive controls, and reusable rich outputs        |
| `index.html`        | Page structure, display copy, responsive layout, projections, and Wind4 utility classes using Tailwind 4 syntax |
| `app.css`           | Theme tokens, custom keyframes, and CSS rules that Wind4 utilities cannot express                               |
| Relative view files | Browser modules, images, fonts, and other presentation assets                                                   |

Do not build page wrappers, layout markup, or style strings in notebook cells
when a Studio view file can own them. This keeps the notebook readable as an
analysis and lets several views reuse the same Python results.

Use `marimo_studio.agents` from Marimo code mode:

```python
import marimo._code_mode as cm
import marimo_studio.agents as studio

ctx = cm.get_context()
notebook = studio.inspect(ctx, include_code=True)
view = studio.ensure_view(ctx, "dashboard")
await studio.activate_view(ctx, view.name)
```

`studio.inspect` compiles the saved notebook and returns its cells,
definitions, references, source positions, native names, and dependency
relationships. It leaves notebook cells unevaluated.

`studio.ensure_view` creates the named view when needed and returns the current
paths. A new view starts with every notebook cell in source order.

`studio.activate_view` targets the Studio tab attached to the current Marimo
code-mode session. When `ensure_view` added the notebook's first Studio view,
the call reloads that native editor into Studio after code mode returns. Later
calls wait for the targeted workspace to complete its normal in-place view
transition.

## Inspect before editing

Read the notebook graph and current view files before choosing content:

```python
for cell in notebook.cells:
    print(cell.index, cell.name, cell.definitions, cell.references)

index_html = (view.root / "index.html").read_text()
app_css = (view.root / "app.css").read_text()
```

Use `include_code=True` when cell names and definitions leave the intended
output unclear.

## Select the projection

Choose the projection from the result the page needs:

```html
<marimo-cell name="analysis"></marimo-cell>
<marimo-output value="revenue_chart"></marimo-output>
<strong mo-value="report.total"></strong>
```

- `<marimo-cell>` includes everything a named cell produced.
- `<marimo-output>` renders one selected Python object through Marimo.
- `mo-value` provides a JSON-compatible value to HTML and JavaScript.

[Use notebook results](notebook-results.md) defines the three projection
forms.

## Bind an unnamed cell

Give an unnamed cell a stable reference with its zero-based notebook position:

```python
binding = studio.bind(ctx, "revenue-chart", 4)
```

Read the current notebook again before setting `overwrite=True` for an
existing alias. The returned binding identifies the selected cell and the
configuration update.

## Edit the web files

Write one complete HTML document with one `#app-shell`. Place every projection
inside that shell. Use Wind4 utilities for regular layout, spacing,
typography, colors, borders, and state variants. The vocabulary follows UnoCSS
Wind4 and Tailwind 4 syntax. Put custom CSS, theme tokens, and keyframes in
`app.css`. Add JavaScript modules, images, fonts, and other assets under
`view.root` and reference them with relative URLs.

Read each file immediately before writing it so the edit incorporates changes
from the Studio workspace or another editor. Saved HTML, CSS, and module
changes refresh the live preview.

## Analyze, repair, and hand off

Analyze the active view after each saved change:

```python
report = await studio.analyze(ctx, view_name=view.name)
for action in report.actions:
    print(action.stage, action.code, action.advice)
```

The report combines three stages:

1. Static checks read the notebook graph and view files.
2. Runtime checks execute the projected notebook code and resolve values.
3. Browser checks confirm that Studio rendered the current source revision and
   report projection, presentation, host, and runtime errors.

Treat `report.actions` as the repair queue. Apply the advice, save the affected
source, and call `studio.analyze` again. Hand off the view when
`report.handoff_ready` is true. A static or runtime pass cannot substitute for
current rendered browser evidence.

Runtime execution waits 60 seconds by default. Give expected remote data or
model setup a larger explicit budget:

```python
report = await studio.analyze(
    ctx,
    view_name=view.name,
    runtime_timeout=120,
)
```

Before handoff, review the notebook diff. Keep changes that define data,
analysis, controls, or reusable outputs. Move page markup, display wording,
layout helpers, CSS strings, and presentation-only formatting into the view
files.

If the view changes during the loop, activate the target explicitly before
analyzing it. Let the activation call return and wait for the page to render:

```python
await studio.activate_view(ctx, "executive")
```

Run the focused analysis in the next code-mode call:

```python
report = await studio.analyze(ctx, view_name="executive")
```

`studio.check` remains available for a static check that leaves notebook cells
unevaluated. It is not the handoff gate.

Inspect the live view during the repair loop. Confirm the reading order,
reactive updates, browser behavior, loading states, controls, plots, tables,
downloads, widgets, and narrow and wide layouts.

## Use the terminal workflow

The command-line interface exposes the same inspection, creation, binding, and
analysis operations for agents working outside Marimo code mode:

```console
uvx marimo-studio inspect analysis.py --include-code --format json
uvx marimo-studio view add analysis.py --name dashboard --format json
MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
  uvx marimo-studio analyze analysis.py \
    --view dashboard \
    --runtime-timeout 120 \
    --format json \
    --diagnostics jsonl
```

The server URL identifies the running Marimo process for this notebook. The
access token comes from that editor session. Prefer the environment variable
so it does not enter shell history.

Without `--server` or `MARIMO_STUDIO_SERVER_URL`, `analyze` still returns
static and runtime diagnostics. It reports the browser stage as
`not-observed`, sets `handoff_ready` to false, adds an action for opening the
view, and exits with code 1.

::: warning Analysis executes notebook code
`analyze` can perform the notebook's configured file, network, database, and
data access. Run it in the notebook environment.
:::

The [Agent API reference](../reference/agent-api.md) defines signatures,
returns, errors, and side effects. The [CLI reference](../reference/cli.md)
defines machine output and exit codes.
