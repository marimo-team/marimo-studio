---
title: Create your first view
description: Create a web view from a saved Marimo notebook and place one reactive result inside it.
---

# Create your first view

Start with Python 3.10 through 3.14, [uv](https://docs.astral.sh/uv/), a Python
project and environment manager, and a saved Marimo notebook such as
`analysis.py`.

::: tip Save a new notebook first
For an untitled notebook, use Marimo **Save As** before creating a view. Studio
follows the saved notebook after Marimo reloads it. The view project then has a
stable location beside that file.
:::

## Create the view project

Preview the filesystem and configuration changes:

```console
uvx marimo-studio view create dashboard \
  --target analysis.py \
  --dry-run
```

Create the view after reviewing the plan:

```console
uvx marimo-studio view create dashboard \
  --target analysis.py
```

The default starter creates this view project beside the notebook:

```text
analysis.py
__marimo__/studio/analysis/
  dashboard/
    view.toml
    index.html
    AGENTS.md
```

`view.toml` records the view provider. `index.html` is the first source
document. `AGENTS.md` gives coding agents project-specific guidance. A
`DESIGN.md` file also appears in Source when you add one to record the
audience, task, and visual decisions for the view.

The first create command can update the notebook's Studio configuration, set
`dashboard` as the default view, and pin the Studio requirement. It prints the
launch command required by the selected starter.

## Open Studio

For the default Vanilla starter, run:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Marimo's `--sandbox` flag resolves the notebook's declared Python dependencies
with uv. It manages the environment and does not isolate untrusted notebook
code from your files or network.

The thin toolbar is available whenever Studio is installed, including before
the notebook has view configuration. Click **Add view** to choose a name and
starter. An unsaved notebook first opens Marimo's Save dialog.

Notebook and Preview open side by side. Use the source action to edit the
view's files beneath Preview. The native agent sidebar remains available.

## Place one notebook cell

Give a producing cell a semantic name:

```python
@app.cell
def sales_summary():
    import marimo as mo

    summary = mo.md("## Revenue is on target")
    summary
    return (summary,)
```

Place the complete cell inside `#app-shell`:

```html
<main id="app-shell" class="studio-view">
  <marimo-cell name="sales_summary"></marimo-cell>
</main>
```

Save `index.html`. Preview renders **Revenue is on target**. A later notebook
run updates the mounted cell through Marimo reactivity. A frontend build error
keeps the last successful artifact visible and reports the affected source
document.

## Run the view

Start the notebook as an application:

```console
uvx --with marimo-studio marimo run analysis.py --sandbox
```

The default view opens at `/`. Another view named `report` opens at `/report/`.

Continue with [Place notebook results in a view](notebook-results.md) for
rendered outputs and browser values. Use [Troubleshoot
Studio](troubleshooting.md) when Studio cannot discover the view or build its
source.
