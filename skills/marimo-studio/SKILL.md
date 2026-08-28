---
name: marimo-studio
description: >-
  Turn a Marimo notebook into focused web pages. Use when an agent needs to
  inspect notebook and page source, edit a page safely, build it, show it in
  Studio, validate the rendered result, run it, or export it.
---

# Author Marimo Studio pages

The notebook computes. The page presents. Studio connects them.

Keep data access, transformations, controls, and reusable results in notebook
cells. Keep page structure, wording, styles, and browser interaction in page
source.

Studio calls each named page a view.

## Work with the current Studio tab

Open the current notebook workspace once in each code-mode execution:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
```

Use `workspace.status()` to inspect configured views before creating one. Use
`workspace.view(name)` for an existing page. Create a page only when the
requested name is absent:

```python
status = await workspace.status()
if not any(item.name == "dashboard" for item in status.views):
    view = await workspace.create_view("dashboard")
```

The default creation path produces one editable HTML page and starter-specific
agent instructions. Inspect installed starting points only when the user asks
for a particular frontend.

## Inspect before editing

Inspect the notebook before changing data, computation, controls, or reusable
results:

```python
notebook = await workspace.inspect_notebook()
```

For a change to one result, include the cells that produce its inputs:

```python
producer = await workspace.inspect_notebook(
    selectors=("summary",),
    include_code=True,
    context="upstream",
)
```

Inspect the page to discover the files Studio exposes:

```python
inspection = await view.inspect()
for document in inspection.documents:
    print(document.path, document.language, document.access)
```

Read `AGENTS.md` when the selected project exposes it:

```python
if any(document.path.as_posix() == "AGENTS.md" for document in inspection.documents):
    instructions = await view.read("AGENTS.md")
    print(instructions.content)
```

The Studio skill owns notebook boundaries, projection semantics, view
lifecycle, and validation. The starter's `AGENTS.md` owns its opinionated
frontend structure, supplied adapters, preferred libraries, and build-specific
conventions. Read both before editing a starter project.

Treat the generated `AGENTS.md` as durable project context. Update it as the
conversation establishes the audience, analytical goal, concrete domain
details, aesthetic direction, interaction priorities, framework or library
preferences, and other decisions that should guide later agents. Keep transient
task status and short-lived implementation notes out of it.

Choose visual direction in this order:

1. Follow the user's explicit style direction.
2. Follow the starter project's `DESIGN.md` when it exists.
3. Otherwise use the current
   [Marimo design guide](https://raw.githubusercontent.com/marimo-team/marimo/refs/heads/main/DESIGN.md)
   as the aesthetic reference.

Read the selected design source before visual authoring. Apply its visual
character, tokens, typography, surfaces, component treatment, and motion
guidance to the page instead of relying on a generic frontend style.

Edit project-relative files whose access is `edit`.

## Save against the version you read

Read each affected file immediately before writing it:

```python
document = await view.read("index.html")
updated = document.content.replace("Current heading", "Quarterly revenue")

await view.write(
    "index.html",
    updated,
    expected_revision=document.revision,
)
```

`SourceConflictError` means a person or another agent saved first. Read the file
again, incorporate both changes, and save against the current revision.

## Place notebook results on the page

Choose the projection from the notebook evidence:

| Notebook result                                               | Page source                                     |
| ------------------------------------------------------------- | ----------------------------------------------- |
| Complete displayed cell, including controls, logs, and errors | `<marimo-cell name="summary"></marimo-cell>`    |
| One Python object rendered by Marimo                          | `<marimo-output value="chart"></marimo-output>` |
| JSON-compatible data consumed by browser code                 | Any element with `mo-value="metrics"`           |

Read the selected cell's `name`, `definitions`, and
`has_output_expression` before writing a projection. When
`has_output_expression` is false, inspect its runtime output before using
`<marimo-cell>`. Use `<marimo-output>` when the cell defines the intended object
but does not display it.

Use a complete cell when the notebook already presents the result:

```html
<marimo-cell name="summary"></marimo-cell>
```

Use one rendered Python object when the page needs a specific result:

```html
<marimo-output value="chart"></marimo-output>
```

Use a JSON-compatible value when browser code will adapt it for this page:

```html
<strong mo-value="metrics.total"></strong>
```

When inspection returns a non-empty cell `name`, use that exact name directly in
`<marimo-cell name="...">`. The native name is already a stable projection
target and needs no binding or alias. Call `workspace.bind()` only when the
complete cell is anonymous and needs a stable page-facing name.

The alias returned by `workspace.bind()` becomes an accepted value for
`<marimo-cell name="...">`. `alias` and `target` are not authored projection
attributes. Literal `name`, `value`, and `mo-value` selectors need no wildcard.
Add `data-marimo-allow="*"` when runtime code intentionally selects a target
that the provider cannot enumerate from source.

Reconsider the projection kind before changing notebook code to make a page
host render. Presentation requirements stay in the view when the notebook
already defines the intended value.

## Build, show, and verify

Build after editing page source:

```python
build = await view.build()
print(build.revision)
```

A failed build leaves the last successful page available. Repair the reported
source issue and build again. Call `view.inspect()` after a failure and read the
diagnostic `message`, `hint`, and source location before editing.

Show the page in the next code-mode execution:

```python
import marimo_studio.agent as studio_agent

await studio_agent.current_workspace().view("dashboard").show()
```

Use the environment's browser tool to exercise the affected controls,
navigation, conditional content, and dynamic results in the same Studio tab.

Validate in another code-mode execution after the page settles:

```python
import marimo_studio.agent as studio_agent

report = await studio_agent.current_workspace().view("dashboard").validate(level="browser")
for issue in report.issues:
    print(issue.severity, issue.message, issue.advice)
```

Repeat edit, build, show, interaction, and validation until `report.ok` is true.
Inspect visible changes at wide and narrow widths.

Browser validation proves that the current page revision and projection hosts
reached their expected lifecycle states. It does not prove spacing, sizing,
responsive layout, scroll choreography, or visual polish. Capture and inspect
the rendered page for visual work. Report the visual check as blocked when the
environment cannot capture or inspect it.

## Run or export

Run through marimo when the notebook needs Python packages, local files,
databases, or server credentials:

```console
uv run --with marimo-studio marimo run notebook.py --sandbox
```

Export when the notebook and its data can run in Pyodide:

```console
marimo-studio view export dashboard \
  --target notebook.py \
  --output dist/dashboard
```

The browser and static export receive the saved notebook source. Review the
notebook, public files, data URLs, and dependencies before publishing.

## Report completion

Report the notebook, view, changed source files, built page revision, and the
static, runtime, and browser validation performed. Leave the notebook and page
runnable.
