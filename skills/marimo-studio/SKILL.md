---
name: marimo-studio
description: >-
  Create, inspect, and refine web views of a marimo notebook. Use for Studio
  view source, live notebook projections, browser verification, selected
  feedback, and running or exporting a named view.
---

# Author Studio views

Studio turns one reactive notebook into named web views. The notebook owns
computation, data, controls, and domain decisions. A view owns its presentation
and browser interaction. Studio owns view projects, builds, and delivery.

## Choose the requested work

| Request                                                                | Start with                                                                          |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Explain or inspect a view                                              | Inspect its source and notebook producers. Keep the task read-only.                 |
| Create a dashboard or presentation                                     | Inspect existing views, choose a starter, build and show a first result.            |
| Build views about a topic that has no notebook                         | Start a new notebook, write its cells through code mode, then create each view.     |
| Change an existing view                                                | Read its project instructions and affected documents, then edit and verify.         |
| Address a [Lens](https://marimo-team.github.io/marimo-lens/) selection | Read [Lens in Studio](references/lens.md) and the installed Lens skill.             |
| Run, publish, or export                                                | Read [delivery](references/delivery.md) before designing controls or exposing data. |
| Recover from a failed command, build, or browser check                 | Match the symptom in [gotchas](references/gotchas.md).                              |

This core contains the ordinary authoring workflow. Read conditional references
when the task needs their detail. Reuse this briefing while the Python
environment and Studio installation remain unchanged.

## Bind to the intended notebook

Live Studio work runs in the notebook's kernel through marimo code mode.
marimo's chat sidebar in **Code Mode** already runs there. A terminal agent
pairs with the running notebook through the `marimo pair` CLI. Run it with
`--with marimo-studio` so uv resolves the marimo release that Studio pins, the
same release the Studio server runs. Read the help once, then list running
notebooks:

```console
uvx --with marimo-studio marimo pair --help
uvx --with marimo-studio marimo pair notebook list
```

Pick the user's notebook and pass its server URL and absolute `path` to every
execution. Run each Python example below as one execution:

```console
uvx --with marimo-studio marimo pair execute --url <URL> --file <PATH> --code-file - <<'PY'
import marimo_studio
print(await marimo_studio.agent.current_workspace().status())
PY
```

The list shows local servers started with `--no-token`. For a server that
requires a token, ask the user for its URL and a token file. List that server
to read the notebook's absolute `path`, and pass `--token-file <PATH>` to every
`pair` command:

```console
uvx --with marimo-studio marimo pair notebook list --url <URL> --token-file <PATH>
```

When the notebook is not running, start it in the background. For a topic with
no notebook, choose a new file name and marimo creates the file. marimo opens a
Studio tab in the user's browser, and the notebook appears in the list once
that tab connects:

```console
uvx --with "marimo-studio[deno]" marimo edit notebook.py --sandbox --watch --no-token
```

`--watch` reloads the notebook in Studio after you or another tool edits the
file. `--no-token` serves the editor on localhost without an access token,
which lets `pair notebook list` find it. Studio needs `marimo-studio` in the
marimo server's environment, as in that command or the notebook project's
dependencies. Its `deno` extra enables the React, Reveal.js, Svelte, and
Notebook Kit starters. `help(marimo._code_mode)` then lists Studio as the
`studio` capability, and sandboxed kernels import the same Studio as the
server. For views across several notebooks, serve their folder as
[setup](references/setup.md#serve-several-notebooks) describes. Create, edit,
and run cells through `marimo._code_mode`, following the `pair --help`
workflow. Without a way to run the notebook, continue with
saved-notebook authoring from a terminal.

Inside notebook code mode, combine connection with the first inspection:

```python
import marimo_studio

workspace = marimo_studio.agent.current_workspace()
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
Build a slide deck from the starter titled `Reveal.js slides`. Resolve
unavailable requirements before building. For an ordinary dashboard,
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
import marimo_studio

await marimo_studio.agent.current_workspace().view("dashboard").show()
```

Rename a view to change its name and URL. It keeps its source and artifacts,
reads as stale until the next build, and stays the default if it was:

```python
import marimo_studio

workspace = marimo_studio.agent.current_workspace()
summary = await workspace.view("report").rename("summary")
await summary.build()
await summary.make_default()
```

`make_default()` serves a view at `/`. To move a view to another starter under
the same name, create the new view under a temporary name and show it. In a
later execution, remove the old view and rename the new one to the old name.

For a notebook outside a Python project, the first view adds a
[PEP 723](https://peps.python.org/pep-0723/) script header, the notebook's
inline dependency list, and declares `marimo-studio` there. A `--sandbox`
launch installs only those dependencies, and marimo records package installs
there only in sandboxed sessions. After creating that view from an unsandboxed
session, declare the notebook's own packages with
`uv add --script notebook.py <package>`.
`marimo-studio doctor --dependencies --target notebook.py` lists imports the
header does not cover.

`show()` activates the user's Studio tab. If build or activation fails, repair
the reported problem before expanding the view. Terminal workflows use the
view's preview URL to open the result.

## Inspect and edit the owning source

Acquire the view and inspect its editable documents:

```python
import marimo_studio

workspace = marimo_studio.agent.current_workspace()
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
[marimo's design guidance](https://raw.githubusercontent.com/marimo-team/marimo/refs/heads/main/DESIGN.md).
Read the chosen design source before styling. Native notebook output is an
opaque subtree, so theme it through projection variables on its host:
`--marimo-cell-font`, `--marimo-cell-heading-font`, `--marimo-cell-foreground`,
`--marimo-cell-accent` for links and marimo controls, and
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

Print selected fields. The full inspection record also contains the complete
saved notebook. Read code for the chosen selector:

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

Add browser packages as the project's `AGENTS.md` describes. An HTML view
references a pinned URL with a `<script src>` tag or a module `import`. React,
Svelte, Reveal.js, and Notebook Kit views build with a frozen `deno.lock`, so a
new package needs one intentional update from the view root with the Deno that
Studio builds with. From code mode, run it through the kernel's Python with the
project's flags, such as `--package-json` for Svelte, then build:

```python
import subprocess
import sys

root = (await view.inspect()).root
add = ["add", "--frozen=false", "--save-exact", "npm:vega-embed@6"]
subprocess.run([sys.executable, "-m", "deno", *add], cwd=root, check=True)
await view.build()
```

## Project notebook results

| Needed result                                            | Authored host                                   |
| -------------------------------------------------------- | ----------------------------------------------- |
| Complete displayed cell, including controls and errors   | `<marimo-cell name="summary"></marimo-cell>`    |
| One Python object rendered by marimo                     | `<marimo-output value="chart"></marimo-output>` |
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
view. Keep native marimo output subtrees opaque and authored hosts inside
`#app-shell`.

Custom renderers must consume current projections, subscribe to updates, and
link every kernel input to the rendered region. Keep labels and source
references on authored regions. Read [projections](references/projections.md)
for adapters, Arrow tables, dynamic selectors, and the complete source-linking
contract. These conventions apply even when Lens is not installed.

## Build, show, and verify

After editing, build and check source freshness in the same call:

```python
import marimo_studio

view = marimo_studio.agent.current_workspace().view("dashboard")
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
import marimo_studio

print(marimo_studio.agent.skill().file("references/projections.md").read_text())
```

Use `help(view)` for operation signatures and
`marimo_studio.agent.plugin()` for the complete plugin bundle. The
[documentation index](https://marimo-team.github.io/marimo-studio/llms.txt)
routes broader guides. Check published APIs against the installed version.
