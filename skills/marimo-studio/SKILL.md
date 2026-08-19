---
name: marimo-studio
description: >-
  Turn Marimo notebooks into custom web pages for dashboards, reports, and
  focused tools. Use when an agent needs to inspect a notebook, create or edit
  named HTML and CSS views, project live cells or Python values, activate a
  view, analyze rendered errors, serve through Marimo, or export WebAssembly.
---

# Author Marimo Studio views

Marimo Studio lets one notebook power several audience-specific web pages.
Keep data access, computation, analytical context, domain rules, controls, and
reusable outputs in notebook cells. Put page structure, display copy, responsive
layout, browser behavior, and presentation styling in the Studio view files.

Read [the capability catalog](references/capabilities.json) before selecting a
Python call or CLI command. It defines the supported operations, parameters,
results, prerequisites, and intentional interface-specific extensions.

## Workflow

1. Read the workspace overview and inspect the notebook.
2. Create or select one named view.
3. Activate that view in the open Studio browser.
4. Choose the complete cells, rich objects, and JSON-compatible values needed by
   the audience.
5. Edit `index.html`, `app.css`, and optional relative assets.
6. Analyze the saved source, isolated notebook runtime, and current rendered
   revision.
7. Repair the ordered actions until `handoff_ready` is true.
8. Inspect the live page and hand off, serve, or export it.

## Choose the interface

Use `marimo_studio.agent` inside Marimo code mode. Its context identifies the
saved notebook and the current Marimo session.

```python
import marimo._code_mode as cm
import marimo_studio.agent as studio

ctx = cm.get_context()
workspace = studio.overview(ctx)
inspection = studio.inspect(ctx, display=True)
setup = studio.ensure_view(ctx, "dashboard")
activation = await studio.activate_view(ctx, setup.name)
```

Let the activation call finish. A first view can reload the native editor into
Studio after code mode releases its execution lock. Run analysis in the next
code-mode call after the page loads:

```python
import marimo._code_mode as cm
import marimo_studio.agent as studio

ctx = cm.get_context()
report = await studio.analyze(ctx, view="dashboard")
for action in report.actions:
    print(action.stage, action.code, action.advice)
```

Use the CLI for a regular coding agent or script. Request JSON on standard
output and JSON Lines diagnostics on standard error.

```console
marimo-studio overview analysis.py --format json
marimo-studio inspect analysis.py --display --format json
marimo-studio view add analysis.py --name dashboard --format json

MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
marimo-studio view activate analysis.py \
  --name dashboard \
  --format json

MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
marimo-studio analyze analysis.py \
  --view dashboard \
  --format json \
  --diagnostics jsonl
```

Pass `--browser-client ID` when several Studio tabs are connected. Activation
fails when the server cannot identify exactly one browser. Keep access tokens in
`MARIMO_STUDIO_ACCESS_TOKEN` so they stay out of process arguments.

## Capability map

| Capability               | Code mode                               | CLI                                                           |
| ------------------------ | --------------------------------------- | ------------------------------------------------------------- |
| Read workspace state     | `studio.overview(ctx)`                  | `marimo-studio overview TARGET`                               |
| Inspect notebook cells   | `studio.inspect(ctx)`                   | `marimo-studio inspect TARGET`                                |
| Create or locate a view  | `studio.ensure_view(ctx, name)`         | `marimo-studio view add TARGET --name NAME`                   |
| Bind a stable cell alias | `studio.bind(ctx, alias, index)`        | `marimo-studio bind TARGET --as ALIAS --cell INDEX`           |
| Activate a view          | `await studio.activate_view(ctx, name)` | `marimo-studio view activate TARGET --name NAME --server URL` |
| Run static checks        | `studio.check(ctx, view_name=name)`     | `marimo-studio check TARGET --view NAME`                      |
| Run the handoff analysis | `await studio.analyze(ctx, view=name)`  | `marimo-studio analyze TARGET --view NAME`                    |
| Remove a view            | Use the CLI                             | `marimo-studio view remove TARGET --name NAME`                |
| Export WebAssembly       | Use the CLI                             | `marimo-studio export TARGET --view NAME --output DIR`        |

Runtime inspection and runtime-enhanced checks are CLI extensions. Code mode
uses `analyze(require_browser=False)` when it needs source and isolated runtime
evidence across configured views without a browser handoff gate.

## Authoring rules

- Read the notebook graph and current view files before editing.
- Use an existing Marimo cell name when it identifies the intended output.
- Bind an alias when an unnamed cell needs a stable HTML reference.
- Keep analytical and computational changes in notebook cells.
- Keep page markup, display wording, layout, CSS, and browser modules in view
  files.
- Use the Server preview while developing against the active Python kernel.
- Treat `report.actions` as the repair queue.
- Require current browser evidence for final handoff.
- Review the notebook diff before finishing so presentation code remains in the
  view.

`marimo-studio view add` may write `[tool.marimo-studio]` metadata and the
`marimo-studio` dependency into the notebook header. `--dry-run` returns the
planned paths and configuration changes without writing them.

## Read the focused references

- Read [View authoring](references/view-authoring.md) before editing HTML, CSS,
  JavaScript, projection hosts, loading states, or relative assets.
- Read [Analysis and handoff](references/analysis-and-handoff.md) before
  executing notebook code, activating browsers, requesting rendered evidence,
  serving, exporting, or reporting completion.

## Handoff

Report the notebook and changed views, the audience and primary task, the view
files changed, the projected cell names and values, configuration changes, and
the source, runtime, and browser evidence collected. Leave the notebook and
each changed view runnable. Finish when focused analysis for every changed view
returns `handoff_ready is True` and the live page passes interaction and layout
inspection.
