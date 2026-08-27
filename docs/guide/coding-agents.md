---
title: Author views with a coding agent
description: Inspect a notebook, edit view source, build, activate, and validate the current page.
---

# Author views with a coding agent

Open the saved notebook once per code-mode execution:

```python
import marimo_studio.agent as studio

workspace = studio.open()
inventory = await workspace.inspect_notebook()
producer = inventory.notebook.named_cells()["summary"]
notebook = await workspace.inspect_notebook(
    include_code=True,
    selectors=(producer.ref, *producer.upstream),
)
view = await workspace.create_view("dashboard")
```

The notebook owns data access, transformations, controls, and reusable results.
The view owns its page structure, copy, styles, and browser interaction.

## Inspect before editing

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
inspection = await view.inspect()
for document in inspection.documents:
    print(document.path, document.language, document.access)
```

Read each affected document immediately before writing. Save through the
revision-aware view API:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
document = await view.read("index.html")
updated = document.content.replace("Current heading", "New heading")
await view.write(
    "index.html",
    updated,
    expected_revision=document.revision,
)
```

Write project-relative paths whose access is `edit`. A concurrent save raises
`SourceConflictError` and keeps the newer disk revision.

Use a native Marimo cell name for a durable view-facing result. An existing
anonymous cell can receive an alias through `workspace.bind(alias, index)`.

[Use notebook results](notebook-results.md) defines complete-cell, rendered
object, and JSON-compatible value mounts.

## Build the view

Build after changing source:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
publication = await view.build()
print(publication.artifact_id)
```

Studio validates the candidate before publishing it. A failed build leaves the
last published page available. Repair diagnostics at their reported source
locations, then build again.

## Activate and exercise the page

Activate in a separate code-mode call so the browser can complete the
transition:

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = workspace.view("dashboard")
activation = await view.activate()
```

Exercise controls, navigation, conditional content, and dynamic mounts used by
the view. When several Studio browsers are connected, the active code-mode
session targets its attached client.

## Validate the current presentation

Run focused validation after the page settles:

```python
import marimo_studio.agent as studio

workspace = studio.open()
report = await workspace.view("dashboard").validate(level="browser")

for action in report.actions:
    print(action.stage, action.code, action.advice)
```

The report combines saved source checks, isolated notebook execution, and
browser evidence for the active presentation. Runtime validation starts the
complete reactive notebook and can use its configured files, network,
databases, and data. Studio then checks the selected projected results.

`report.actions` contains errors and warnings. Errors make `report.ok` false.
Evaluate warnings against the requested workflow. For browser validation,
`report.handoff_ready` confirms that the evidence belongs to one current
presentation. Reinspect the named source, rebuild, reactivate when needed, and
validate again.

## Use the terminal workflow

Use the CLI outside code mode:

```console
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

Activation and browser validation connect to a running Studio server. Supply
`MARIMO_STUDIO_ACCESS_TOKEN` through the parent process or a secret manager.

[Agent API reference](../reference/agent-api.md) lists exact method signatures.
[Run, export, and share](run-and-share.md) covers Server, WebAssembly, and
static delivery.
