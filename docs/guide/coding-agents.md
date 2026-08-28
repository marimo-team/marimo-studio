---
title: Author with a coding agent
description: Inspect notebook and page source, make a revision-safe edit, show the result, and validate the rendered page.
---

# Author with a coding agent

Marimo Studio ships an Agent Skill and a Python API bound to the current
code-mode notebook and Studio tab. The agent works with the same notebook,
source files, builds, and Preview that a person sees.

The workflow has five visible actions:

```text
inspect -> edit -> build -> show -> verify
```

Open the current workspace once in each code-mode execution:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
```

The inspect, edit, and build snippets use these `workspace` and `view` handles
within the same execution.

## Inspect the notebook and page

Read the notebook inventory before changing its analytical model:

```python
notebook = await workspace.inspect_notebook()
print(notebook.notebook.named_cells())
```

When a requested change reaches into a result's computation, ask for that cell
and every cell that produces its inputs:

```python
producer = await workspace.inspect_notebook(
    selectors=("sales_summary",),
    include_code=True,
    context="upstream",
)
```

Inspect the selected page to find the files Studio exposes for editing:

```python
inspection = await view.inspect()
for document in inspection.documents:
    print(document.path, document.language, document.access)
```

Choose project-relative files whose access is `edit`.

## Edit without overwriting a newer save

Read the file immediately before writing it. Pass the source version returned
by that read:

```python
document = await view.read("index.html")
updated = document.content.replace("Current heading", "Quarterly revenue")

await view.write(
    "index.html",
    updated,
    expected_revision=document.revision,
)
```

If a person or another agent saved first, Studio raises `SourceConflictError`
and preserves the newer file. Read it again, incorporate both changes, and save
against the new revision.

## Build the page

```python
build = await view.build()
print(build.revision)
```

Studio validates the complete browser output before replacing Preview. A failed
build keeps the last successful page available and reports source-located
issues for repair.

## Show the page in Studio

Run this in the next code-mode execution so the Studio tab can complete the
transition:

```python
import marimo_studio.agent as studio_agent

view = studio_agent.current_workspace().view("dashboard")
await view.show()
```

Use the browser tool provided by the coding environment to exercise controls,
navigation, conditional content, and dynamic results in that same Studio tab.

## Verify the rendered result

Run browser validation after the page settles and its relevant interactions
have been exercised:

```python
import marimo_studio.agent as studio_agent

report = await studio_agent.current_workspace().view("dashboard").validate(level="browser")
if not report.ok:
    for issue in report.issues:
        print(issue.message, issue.advice)
```

A successful report belongs to the current saved source, runtime, Studio tab,
and rendered page. Repair each reported issue, then repeat build, show,
interaction, and validation.

Use [`marimo_studio.authoring`](../reference/python-api.md) for scripts that
work with a saved notebook outside code mode. Use the [CLI
reference](../reference/cli.md) for terminal automation.
