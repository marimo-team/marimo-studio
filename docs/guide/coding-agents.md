---
title: Author with a coding agent
description: Edit notebook and view source through Studio or filesystem tools, show the result, and inspect the rendered view with browser tools.
---

# Author with a coding agent

Marimo Studio ships an [Agent Skill](https://agentskills.io/), a portable set
of instructions that teaches a coding agent how to use Studio, and a Python API
bound to the current [Marimo code mode](https://docs.marimo.io/guides/editor_features/tools/#code-mode)
notebook and Studio tab. Code mode gives the agent a Python execution inside
the live notebook kernel. The agent works with the same source documents,
builds, and Preview that a person sees.

Use this loop:

```text
inspect -> edit -> build -> show -> verify
```

## Point to a result with Marimo Lens

[Marimo Lens](https://marimo-team.github.io/marimo-lens/) is an optional companion
for selecting a rendered result, adding a note, and giving a coding agent its
producing notebook context and image. For feedback in a Server view, install
version 0.2.2 or newer in the notebook's Python environment:

```sh
uv pip install "marimo-lens>=0.2.2"
```

For sandboxed notebooks, also declare `marimo-lens>=0.2.2` in the script's
dependencies. Restart a running notebook after installing or upgrading Lens.

When the notebook imports no Lens of its own, Marimo mounts one in the notebook.
The development preview reuses that same Lens, so the Notebook pane and the
preview each show a dock, and selections from either one reach the agent
together. No Lens cell or projection is needed for this workflow.

To project an explicitly authored Lens into another Server view, define one value:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
None
```

Project it into the view:

```html
<marimo-output value="studio_lens"></marimo-output>
```

The final `None` keeps the notebook cell's output empty so the dock appears on
the projected view. Studio skips Marimo's automatic Lens in a notebook that
imports Lens, so `studio_lens` is the notebook's only Lens. Select mode shows the cell or value source beside the
pointed result. An agent can inspect the selection through Lens in the same
live kernel, edit through Studio, verify the result, and resolve the note.

Native cell, rich-output, and value projections carry their sources
automatically. For React, Svelte, or other custom JavaScript rendering, link each
meaningful result to its actual projection inputs as described in
[Trace custom JavaScript rendering](../reference/projections.md#trace-custom-javascript-rendering).
The Lens package supplies the selection workflow. Studio supplies the projection
metadata.

Studio makes authored HTML inside `#app-shell` selectable, including copy and
layout without notebook inputs. Lens groups a click into the nearest section,
card, figure, or block and keeps the clicked child's text, path, and relative
bounds as a compact DOM hint. Native notebook outputs retain their own targets.

Tune grouping for one view on its shell:

```html
<main id="app-shell" data-marimo-lens-scope=".card, header, figure">
  <!-- Ordinary HTML inside these regions is selectable. -->
</main>
```

Mark a region with `data-marimo-lens-target` when it should take precedence over
smaller nested targets:

```html
<header
  id="intro"
  data-marimo-lens-target
  data-marimo-lens-label="Introduction"
  data-marimo-lens-render-source='{"path":"index.html"}'
>
  <h1>Regional outlook</h1>
</header>
```

A region without notebook inputs retains its note and image with empty notebook
provenance. An explicit render-source reference tells the agent which file to edit.
Keep the ID stable across rebuilds so Lens can reconnect the feedback.

Use the public [Lens documentation](https://marimo-team.github.io/marimo-lens/)
for its agent API and feedback workflow. The
[source repository](https://github.com/marimo-team/marimo-lens) contains its
implementation and contributor documentation.

## Open the current workspace

Create the handles once in each code-mode execution:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
```

The remaining snippets use these handles within the same execution. Reimport
`marimo_studio.agent` and reacquire the handles in every new execution.

For a new view, project an existing notebook result, build, and show it before
expanding the analysis or layout. Continue with small visible changes through
the same loop.

## Inspect before editing

Read the notebook inventory:

```python
notebook = await workspace.inspect_notebook()
print(notebook.notebook.named_cells())
```

When a request reaches into a result's computation, inspect the producing cell
and its upstream context:

```python
producer = await workspace.inspect_notebook(
    selectors=("sales_summary",),
    include_code=True,
    context="upstream",
)
```

Inspect the selected view to find the source documents exposed by its view
provider:

```python
inspection = await view.inspect()
for document in inspection.documents:
    print(document.path, document.language, document.access)
```

Read `AGENTS.md` and `DESIGN.md` when present before changing the project.
Use Studio's guarded writes for catalog documents with `access="edit"`, or edit
source directly under `inspection.root` with filesystem tools. Reinspect after
either editing path. `files` records the observed source and build-input files,
and `changes_since(previous)` compares two complete inventories for the same
view owner.

For a multi-file edit, use `view.hold_publication(owner="source-refactor")` and
retain its token across executions. Release with
`view.release_publication(token)` when the source is ready, then build. The
hold expires after 300 seconds by default. It delays replacement publication
while files remain editable. See [Manage view source](manage-source.md) for
filesystem editing, hold duration, and checkpoint recovery.

## Write against the current revision

Read a source document immediately before replacing it:

```python
document = await view.read("index.html")
updated = document.content.replace("Current heading", "Quarterly revenue")

await view.write(
    "index.html",
    updated,
    expected_revision=document.revision,
)
```

If another author saved first, Studio raises `SourceConflictError` and keeps
the newer source. Read it again, incorporate both changes, and write against
the new revision.

## Build and show

```python
build = await view.build()
print(build.revision)
```

Studio validates the complete candidate before publishing it. A failed build
keeps the last successful artifact in Preview. Inspect `latest_build` and its
diagnostics for the failed attempt. `build` identifies the retained artifact,
and `published_project_revision` identifies its source inputs.

Run `show()` in the next code-mode execution so the Studio tab can complete
the transition:

```python
import marimo_studio.agent as studio_agent

view = studio_agent.current_workspace().view("dashboard")
await view.show()
```

Exercise controls, navigation, conditional content, and dynamic results in the
same Studio tab.

## Verify the rendered view

Open a top-level preview URL with your preferred browser tool:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
url = await view.preview_url(runtime="server")
print(url)
```

Finish this code-mode execution before the browser waits for notebook output.
Run browser interactions and waits through an external tool or interpreter
when they need the notebook kernel to execute. A synchronous wait inside code
mode can block the work being awaited.

A view build compiles frontend source. After editing notebook Python, execute
the changed cells in the live notebook before inspecting their projected
results. Use Marimo's **Run all** action when the change needs the complete
notebook. Isolated runtime validation checks a separate process and leaves the
live notebook session unchanged.

Use ordinary browser waits for `html[data-marimo-studio-state="ready"]`, then
assert the application's expected content and behavior. Studio readiness covers
its runtime and mounted projections. Framework rendering, charts, slides, and
remote requests also need application assertions. A non-busy region can still
display an error.

Read `document.documentElement.dataset.marimoStudioRevision` for the committed
presentation revision. Request `preview_url(runtime="server", exact=True)` when
a check must use the current revision. A different revision or unbuilt or failed
view source produces HTTP 409, including when a previous artifact is retained. Use the stable URL and reload after builds during normal iteration.

Check `view.inspect()` for source and build freshness, since a failed build
retains the previous working artifact. Run `view.validate(level="static")` for
source checks or `level="runtime"` to execute the saved notebook in an isolated
process.

After changing a control, wait for its dependent metric, text, or chart to
update. The control's selected value alone does not prove reactive completion.
If readiness stalls, read the visible status or error and inspect console and
network failures before retrying. Follow a request to execute changed cells in
the live notebook.

Wait for application transitions to settle before capturing wide and narrow
screenshots. Inspect the images with the agent's image-capable tool and use
visual findings for the next edit. At narrow widths, check readable text and
usable controls as well as overflow. Saving a path alone does not check layout.
Exercise the relevant controls and navigation. Repeat edit, build, reload,
interaction, and assertions until the expected result passes.

## Verify the delivery visitors will use

Use [Run or export a view](run-and-share.md) to select Python, Browser, or
Prepared delivery. A live Python preview does not prove a static export's
behavior. For Prepared delivery, declare the finite control states, run
preflight, serve the completed export over HTTP, and exercise those states in
the browser. Include a failed state change when the interface needs recovery.

Use [`marimo_studio.authoring`](../reference/python-api.md) for scripts that
open a saved notebook outside code mode. Use the [CLI
reference](../reference/cli.md) for terminal automation.
