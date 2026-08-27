---
name: marimo-studio
description: >-
  Turn Marimo notebooks into custom web views. Use when an agent needs to
  create or inspect a view, edit frontend source, mount notebook results,
  build, activate, validate, serve, or export a view.
---

# Author Marimo Studio views

Marimo Studio lets one notebook power several custom views. Keep data access,
transformations, controls, and reusable results in notebook cells. Keep page
structure, copy, styles, and browser interaction in view source.

## Route by capability

Use the smallest workflow that answers the request.

| Request                     | Operations                                                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------ |
| Inspect a notebook or view  | `workspace.inspect_notebook()`, `workspace.status()`, `view.inspect()`, and `view.read()`  |
| Author a view               | Inspect, choose a starter when creation is needed, write revision-aware source, then build |
| Validate saved source       | `validate(level="static")`                                                                 |
| Validate notebook execution | `validate(level="runtime")`                                                                |
| Validate the rendered page  | Activate the requested view, exercise its interactions, then `validate(level="browser")`   |
| Serve or export             | Validate the delivery prerequisites, build the production profile, then run or export      |

Inspection is a read workflow. Authoring owns creation and source mutation.
Browser activation belongs to browser-facing work.

## Use code mode

Open the current notebook workspace in each code-mode execution:

```python
import marimo_studio.agent as studio

workspace = studio.open()
inventory = await workspace.inspect_notebook()
producer = inventory.notebook.named_cells()["summary"]
notebook = await workspace.inspect_notebook(
    include_code=True,
    selectors=(producer.ref, *producer.upstream),
)
```

When authoring requires a new view, inspect the starter catalog and create the
view explicitly:

```python
import marimo_studio.agent as studio

workspace = studio.open()
starters = await workspace.starters()
view = await workspace.create_view(
    "dashboard",
    starter="marimo-studio/vanilla:default",
)
```

Inspect the returned documents before editing:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
inspection = await view.inspect()
for document in inspection.documents:
    print(document.path, document.language, document.access)
```

Edit project-relative paths whose access is `edit`. Read and write through the
revision-aware view API:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
document = await view.read("index.html")
updated_content = document.content.replace("Current heading", "New heading")
await view.write(
    "index.html",
    updated_content,
    expected_revision=document.revision,
)
```

Read immediately before writing so the change incorporates work from Studio or
another editor. When `SourceConflictError` includes a revision, read again and
resolve against that disk revision. Inspect and preserve `external_recovery`
before retrying when the error supplies that path.

Build and activate in separate code-mode calls:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
publication = await view.build()
print(publication.artifact_id)
```

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
activation = await view.activate()
```

Exercise the rendered interactions, then request current evidence:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
report = await view.validate(level="browser")
for action in report.actions:
    print(action.stage, action.code, action.advice)
```

Use `workspace.view(name)` in later calls to recover the same view handle.

## Use the CLI

Use the CLI when code mode is unavailable:

```console
marimo-studio starters --format json
marimo-studio view create dashboard --target notebook.py --format json
marimo-studio view inspect dashboard --target notebook.py --format json
marimo-studio view build dashboard --target notebook.py --format json
marimo-studio view activate dashboard \
  --target notebook.py \
  --server http://localhost:2718 \
  --browser-client CLIENT_ID
marimo-studio validate dashboard --target notebook.py \
  --level browser \
  --server http://localhost:2718 \
  --browser-client CLIENT_ID
```

Request JSON on standard output and JSON Lines diagnostics on standard error.
A secret manager or the parent process should supply
`MARIMO_STUDIO_ACCESS_TOKEN` when the server requires authentication.

## Serve or export

Serve the configured notebook through Marimo when its Python environment is
available to the audience:

```console
uv run --with marimo-studio marimo run notebook.py --sandbox
```

Export one view for static hosting when the notebook and dependencies run in
Pyodide:

```console
marimo-studio view export dashboard \
  --target notebook.py \
  --output dist/dashboard
```

The export contains notebook source. Review the output boundary before
publishing credentials, private data paths, or server-dependent code.

## Work with notebook results

View source can mount a complete cell, render one Python object through Marimo,
or read a JSON-compatible value. Inspect the selected starter and existing
source before adding hosts. Use ordinary source-language control flow for
dynamic layouts.

Use native Marimo cell names for durable view-facing results. A configured
alias can name an existing anonymous cell.

Read [View authoring](references/view-authoring.md) for source documents,
projection hosts, build behavior, and conflicts.

## Validate and hand off

`report.ok` is false when validation has an error. Warnings remain in
`report.actions` for task-specific judgment. `report.handoff_ready` reports
whether the requested evidence belongs to one coherent current presentation.
When several browsers are connected, activation must identify the intended
client.

Read [Validation and handoff](references/validation-and-handoff.md) before
executing notebook code, requesting browser evidence, serving, exporting, or
reporting completion.

For authored browser-facing changes, build the changed view, activate the
target browser, exercise the affected interactions, and validate the active
presentation. Repair errors. Resolve warnings that affect the requested
capability. Confirm `handoff_ready` when browser evidence is required. Inspect
visible UI changes at narrow and wide widths.

Report the notebook, view, changed documents, publication identity, and the
static, runtime, and browser evidence used to validate the result.
