---
title: Author with a coding agent
description: Inspect notebook and view source, make a revision-safe edit, show the result, and validate the rendered view.
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

## Open the current workspace

Create the handles once in each code-mode execution:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
```

The remaining snippets use these handles within the same execution.

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

Edit project-relative documents whose access is `edit`. Read `AGENTS.md` and
`DESIGN.md` when present before changing the project.

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
keeps the last successful artifact in Preview.

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

Run browser validation after the relevant interactions settle:

```python
import marimo_studio.agent as studio_agent

report = await studio_agent.current_workspace().view("dashboard").validate(
    level="browser"
)
if not report.ok:
    for issue in report.issues:
        print(issue.message, issue.advice)
```

The report belongs to the current saved notebook, source revisions, runtime,
Studio tab, and presentation. Repair each issue, then repeat build, show,
interaction, and validation.

Use [`marimo_studio.authoring`](../reference/python-api.md) for scripts that
open a saved notebook outside code mode. Use the [CLI
reference](../reference/cli.md) for terminal automation.
