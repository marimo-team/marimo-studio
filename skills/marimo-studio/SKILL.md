---
name: marimo-studio
description: >-
  Create, inspect, and refine web views of a Marimo notebook. Use for Studio
  view source, live notebook projections, browser verification, selected
  feedback, and running or exporting a named view.
---

# Author Marimo Studio views

Studio turns one reactive notebook into named web views. The notebook owns
computation, data, controls, and domain decisions. A view owns its presentation
and browser interaction. Studio owns view projects, builds, and delivery.

## Choose the requested work

| Request                            | Start with                                                                          |
| ---------------------------------- | ----------------------------------------------------------------------------------- |
| Explain or inspect a view          | Inspect its source and notebook producers. Keep the task read-only.                 |
| Create a dashboard or presentation | Inspect existing views, choose a starter, build and show a first result.            |
| Change an existing view            | Read its project instructions and affected documents, then edit and verify.         |
| Address a Lens selection           | Read [Lens in Studio](references/lens.md) and the installed Lens skill.             |
| Run, publish, or export            | Read [delivery](references/delivery.md) before designing controls or exposing data. |

This core contains the ordinary authoring workflow. Read conditional references
when the task needs their detail. Reuse this briefing while the Python
environment and Studio installation remain unchanged.

## Bind to the intended notebook

Live Studio work runs in the notebook's kernel through Marimo code mode. Two
hosts provide it:

- Marimo's chat sidebar in **Code Mode** already runs the agent in the
  notebook's kernel.
- An external agent pairs with a running notebook through the `marimo-pair`
  skill, which owns finding, starting, and connecting to notebook servers and
  executing code in them.

Studio adds one requirement to either host. The Marimo server must run with
`marimo-studio` installed, for example through `uvx --with marimo-studio` or
the notebook project's dependencies. Sandboxed kernels then import the same
Studio as the server. When neither host is connected, ask the user to open the
notebook in Studio and connect one. Saved-notebook authoring continues from a
terminal as described below.

Inside notebook code mode, combine connection with the first inspection:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
status = await workspace.status()
print(status)
```

Reimport and reacquire the workspace and view in every code-mode execution.
Scratch variables and handles may not survive between calls. Use the user's
intended notebook and view, including when another view is currently visible.

From a terminal, use `marimo_studio.authoring.open_workspace("notebook.py")`
or CLI commands with `--target notebook.py`. Preview URL lookup also needs the
running `server` URL or `--server`. See [setup](references/setup.md) for
connection, environment selection, or missing capabilities.

`workspace.inspect_notebook()` inspects saved source. Its optional runtime
inspection executes an isolated process. Neither is a snapshot of the live
kernel, even when the workspace comes from code mode. Use the notebook's
code-mode integration to inspect live values and execute changed cells.

## Select or create the view

Reuse the requested existing view. Create a view only when the task calls for
one. For a first view, build and show the starter before substantial analysis
or visual refinement so the user can follow the result as it develops.

When a frontend or presentation framework is requested, inspect installed
starters and their availability:

```python
starters = await workspace.starters()
for starter in starters:
    print(starter.id, starter.title, starter.availability)
```

Pass the selected returned `starter.id` as `starter=` to `create_view()`.
Resolve unavailable requirements before building. For an ordinary dashboard,
the default starter creates an editable HTML page with notebook output hosts:

```python
if any(item.name == "dashboard" for item in status.views):
    view = workspace.view("dashboard")
else:
    view = await workspace.create_view("dashboard")
await view.build()
```

Use the requested name in place of `dashboard`. Finish that execution, then
activate the view in a fresh code-mode call:

```python
import marimo_studio.agent as studio_agent

await studio_agent.current_workspace().view("dashboard").show()
```

`show()` activates the user's Studio tab. If build or activation fails, repair
the reported problem before expanding the view. Terminal workflows use the
view's preview URL to open the result.

## Inspect and edit the owning source

Acquire the view and inspect its editable documents:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
inspection = await view.inspect()
print(inspection.root)
for document in inspection.documents:
    print(document.path, document.language, document.access)
if any(doc.path.as_posix() == "AGENTS.md" for doc in inspection.documents):
    print((await view.read("AGENTS.md")).content)
```

The project's `AGENTS.md` owns its actual source structure, adapters,
dependencies, and toolchain. Preserve its accumulated decisions. Record durable
audience, analytical goals, interaction priorities, and design choices there.
Keep transient task status out of project instructions.
Use the user's visual direction, then `DESIGN.md` if inspection lists it, then
[Marimo's design guidance](https://raw.githubusercontent.com/marimo-team/marimo/refs/heads/main/DESIGN.md).
Read the chosen design source before styling. Native notebook output is an
opaque subtree, so theme it through projection variables on its host:
`--marimo-cell-font`, `--marimo-cell-heading-font`, `--marimo-cell-foreground`,
`--marimo-cell-accent` for links and Marimo controls, and
`--marimo-cell-font-size` for Markdown. The
[styling guide](https://marimo-team.github.io/marimo-studio/guide/styling.md)
lists the complete set.

Discover available cells with a compact inventory, then inspect the relevant
producers before changing notebook results or projecting them:

```python
notebook = await workspace.inspect_notebook()
for cell in notebook.cells:
    print(cell.name, cell.definitions, cell.has_output_expression)
```

Print selected fields rather than the full inspection record, which also
contains the complete saved notebook. Read code for the chosen selector:

```python
producer = await workspace.inspect_notebook(
    selectors=("summary",), include_code=True, context="upstream"
)
for cell in producer.cells:
    print(cell.name, cell.definitions, cell.code)
```

Substitute a selector discovered in the notebook. For analytical changes, read
[notebook analysis](references/notebook-analysis.md). Keep data loading,
transformations, controls, and shared results in notebook cells.

Use guarded writes for existing editable documents. This example changes a
heading in a Vanilla view after reading its current content:

```python
document = await view.read("index.html")
updated = document.content.replace("Current heading", "Quarterly revenue")
await view.write("index.html", updated, expected_revision=document.revision)
```

Confirm the intended text exists before replacing it. A `SourceConflictError`
requires a fresh read and reconciliation with the concurrent edit. Filesystem
tools can also edit `inspection.root`. Inspect again after external changes.
Keep generated `.artifacts/` files under Studio's ownership.

For new files, manifest changes, multi-file edits, or recovery, read
[authoring](references/authoring.md). Publication holds delay artifact
replacement but do not make source writes atomic. Keep source organized around
focused components and use the project's formatter when available.

## Project notebook results

| Needed result                                            | Authored host                                   |
| -------------------------------------------------------- | ----------------------------------------------- |
| Complete displayed cell, including controls and errors   | `<marimo-cell name="summary"></marimo-cell>`    |
| One Python object rendered by Marimo                     | `<marimo-output value="chart"></marimo-output>` |
| JSON-compatible data or eager dataframe for browser code | `<strong mo-value="metrics.total"></strong>`    |

Read a cell's `name`, `definitions`, and `has_output_expression` before choosing
its projection. Prefer the exact existing cell name. Bind an alias with
`workspace.bind()` only for an anonymous cell that needs a stable target. If a
cell defines an object but does not display it, project the object with
`marimo-output`. Check runtime output before projecting a cell with no output
expression.

Never copy notebook-derived values or analytical claims into frontend source.
Project metrics, dates, categories, chart inputs, and analytical prose from
named notebook results. Literal UI copy and design constants can stay in the
view. Keep native Marimo output subtrees opaque and authored hosts inside
`#app-shell`.

Custom renderers must consume current projections, subscribe to updates, and
link every kernel input to the rendered region. Keep labels and source
references on authored regions. Read [projections](references/projections.md)
for adapters, Arrow tables, dynamic selectors, and the complete source-linking
contract. These conventions apply even when Lens is not installed.

## Build, show, and verify

After editing, build and check source freshness in the same call:

```python
import marimo_studio.agent as studio_agent

view = studio_agent.current_workspace().view("dashboard")
build = await view.build()
inspection = await view.inspect()
print(build.revision, inspection.freshness)
print(await view.preview_url(runtime="server"))
```

`inspect()` reports development freshness. For a run-mode server, build with
`profile="production"`, request `preview_url(runtime="server", exact=True)`, and
verify the displayed revision and application using [verification](references/verification.md).
Failed builds retain the last successful artifact. Repair diagnostics before
accepting a working preview as evidence of the edited source.

Building a view does not execute changed notebook Python. Run changed cells
in the live notebook before checking their results. Static validation checks
saved source. `view.validate(level="runtime")` runs isolated execution and
cannot prove that the live session updated.

Finish code-mode execution before opening its preview URL or waiting on the
browser. Kernel-dependent browser interactions and waits belong in an external
tool or interpreter. Keep the edit-mode notebook session open.

Wait for `html[data-marimo-studio-state="ready"]`, then verify the actual
application. Studio readiness does not prove a chart rendered or a control's
dependent values updated. For exact URLs, authentication, revision comparison,
or stalled readiness, read [verification](references/verification.md).

Exercise affected controls and navigation. Check projected values, analytical
prose, and custom charts after a relevant input changes. Inspect wide and
narrow screenshots with an image-capable tool for legible text, usable controls,
and overflow. Report unavailable visual checks accurately. Leave the requested
view visible after verification.

Before delivery, choose [the runtime](references/delivery.md). The Python runtime keeps
source and credentials on the server while sending projected outputs to
visitors. The Browser runtime sends notebook source and browser-accessible data
to visitors. The Prepared runtime sends prepared outputs and public files,
including unselected states. Keep secrets out of browser delivery. A live preview does not prove
an exported site's behavior. Verify the actual export over HTTP.

Report the notebook, view, changed source, artifact revision, and checks
performed. Keep the notebook and view runnable.

## Read a conditional reference

Read a packaged reference from the same installation:

```python
import marimo_studio.agent

print(marimo_studio.agent.skill().file("references/projections.md").read_text())
```

Use `help(view)` for operation signatures and
`marimo_studio.agent.plugin()` for the complete plugin bundle. The
[documentation index](https://marimo-team.github.io/marimo-studio/llms.txt)
routes broader guides. Check published APIs against the installed version.
