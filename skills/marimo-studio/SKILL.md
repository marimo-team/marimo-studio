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
Treat the notebook as the durable analytical source and each Studio view as an
adaptable presentation of that source. Preserve the notebook source when its
existing cells already expose the data and results the view needs.

Add notebook code for new datasets, major computations, analytical definitions,
assumptions, metrics, domain decisions, shared reactive controls, and results
reused across views. View JavaScript may filter, sort, group, restructure,
format, and derive display-ready arrays and objects from existing projected
values when that work serves one view.

The boundary follows analytical ownership. A change that establishes shared
meaning, fetches a new dataset, or produces a reusable result belongs in the
notebook. A change that adapts existing values for one audience can stay in the
view. Browser code can consume JSON-compatible notebook values through
`mo-value` and `marimo-value-updated`, then render them with browser APIs or
frontend libraries.

Read [the capability catalog](references/capabilities.json) before selecting a
Python call or CLI command. It defines the supported operations, parameters,
results, prerequisites, and intentional interface-specific extensions.

## Workflow

1. Read the workspace overview and inspect the notebook.
2. Create or select one named view.
3. Activate that view in Build before substantial authoring, even when it still
   contains the starter document.
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

Activate as soon as `ensure_view` returns. The starter document makes the
user's request visible, and subsequent saves show progress in the same active
preview.

Activation selects Build in the targeted Studio workspace. Reactivating the
current view reloads every prepared preview runtime and clears its ready status
until the refreshed document reports back. Use the same call when the visible
page looks stale or stuck.

Let the activation call finish. First-view activation opens Studio around the
existing native editor and keeps its code-mode session connected. Run analysis
in the next code-mode call:

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
- Bind an alias for an isolated unnamed cell when it needs a stable HTML
  reference.
- When a large notebook would need many aliases for complete cell projections,
  give its stable view-facing producer cells semantic native names. Name the
  small set of cells that express durable concepts and leave incidental cells
  anonymous.
- Preserve the notebook when current cells already expose the required data and
  analytical results.
- Add notebook code for new datasets, major computations, domain decisions, or
  results intended for reuse across views.
- Keep view-specific filtering, restructuring, formatting, display-ready data,
  markup, copy, interaction, layout, styling, and transient UI state in the
  view.
- Keep small view-specific JavaScript in an inline `<script type="module">` in
  `index.html`. Extract `app.js` or additional modules when the code grows
  enough to benefit from separate organization, reuse, or testing.
- Use the Server preview while developing against the active Python kernel.
- Treat `report.actions` as the repair queue.
- Run focused analysis immediately before handoff and require current browser
  evidence.
- Review the notebook diff before finishing so presentation code remains in the
  view.

### Mount Lens for view feedback

Install `marimo-lens` in the Marimo environment before mounting it. Read its
packaged Agent Skill from Python:

```python
from marimo_lens.agent import agent_skill

skill = agent_skill()
print(skill.body)
```

Use the Marimo Lens skill when a person should point to a projected result or
authored page region.

```python
from marimo_lens import Lens
from marimo_studio import LENS_TARGET_SELECTOR

lens = Lens(
    dom_selector=(
        f"{LENS_TARGET_SELECTOR}, "
        "#app-shell :is(header, section, article)"
    ),
)
lens
```

Render that notebook value inside the active view:

```html
<marimo-output value="lens"></marimo-output>
```

`LENS_TARGET_SELECTOR` is Studio's projection-host policy for Lens. Compose
additional HTML regions into the same CSS selector when layout, copy, styling,
or browser behavior can receive feedback. Keep those regions bounded to
meaningful page roots.

Write semantic `name`, `value`, and `mo-value` references in the view. Studio
resolves current producer cell IDs at runtime and exposes them as host metadata.
Lens reads the generic target and producer metadata selected by the supplied
CSS policy. Producer IDs stay out of authored HTML.

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

Immediately before handoff, activate each changed view and run focused analysis
in the next code-mode call. Repair every reported action and repeat until
`handoff_ready is True`. Inspect the live page after the final pass. If the page
still looks stale or broken, reactivate the current view, rerun focused
analysis, and inspect the refreshed result.

Report the notebook and changed views, the audience and primary task, the view
files changed, the projected cell names and values, configuration changes, and
the source, runtime, and browser evidence collected. Leave the notebook and
each changed view runnable. Finish when focused analysis for every changed view
returns `handoff_ready is True` and the live page passes interaction and layout
inspection.
