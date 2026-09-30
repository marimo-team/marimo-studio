---
title: Use Studio in marimohub
description: Add Studio to a marimohub notebook, create a view in the hub editor, and serve it as the notebook's app.
---

# Use Studio in marimohub

[marimohub](https://marimohub.docs.marimo.io/) is a self-hosted platform that
stores marimo notebooks and runs each session in a sandbox. When a notebook
declares `marimo-studio`, the hub installs Studio into the sandbox, the
notebook page opens the Studio authoring workspace, and **Run as app** serves
the notebook's default view.

![A marimohub notebook page with the notebook beside a live dashboard Preview](/screenshots/marimohub/studio-workspace.png)

## Persist view projects

marimohub copies `notebook.py` and `pyproject.toml` into each sandbox and saves
them when the session ends. Studio writes view projects to the same sandbox
workspace, and the hub saves those files only when the deployment sets:

```console
MARIMOHUB_PERSIST_WORKSPACE=workspace
```

With the default `source` value, every new sandbox starts without the notebook's
views. The editor offers **Add view** again, and **Run as app** serves the
notebook as a plain marimo app. See the hub's
[configuration reference](https://marimohub.docs.marimo.io/configuration) for
the setting.

The hub page frames the notebook from another origin. marimohub's notebook
bridge declares the hub origin with a `data-parent-origin` script attribute, and
Studio adds that origin to the `frame-ancestors` policy of the workspace and its
native editor. See [Process settings](../reference/configuration.md#process-settings)
for that contract.

## Add Studio to the notebook

In the project's notebook list, open the notebook's actions menu, choose
**Browse files**, and open `notebook.py`. Add this header at the top of the file
and click **Save**:

```python
# /// script
# dependencies = ["marimo-studio>=0.2.2"]
#
# [tool.marimo-studio]
# default = "dashboard"
# view_root = "studio"
# ///
```

![Browse files with the Studio header added to notebook.py](/screenshots/marimohub/notebook-header.png){width=520}

The header is a [PEP 723](https://peps.python.org/pep-0723/) script block,
which stores dependencies and tool configuration inside the notebook file:

| Entry          | Effect in marimohub                                                                                                                                 |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dependencies` | The hub [installs inline dependencies](https://marimohub.docs.marimo.io/sandbox-image#inline-dependencies) when a sandbox starts                    |
| `default`      | Names the view that **Add view** proposes and **Run as app** serves                                                                                 |
| `view_root`    | Stores view projects in `studio/` beside the notebook. The default location, `__marimo__/studio/notebook/`, sits in a directory the hub never saves |

**Browse files** is read-only while an editor session runs, so stop the session
first. The saved header creates a new notebook version. Dependency changes apply
at the next sandbox start, and the first start after adding Studio spends extra
time installing it. For a Git-synced notebook, add the header in the repository
and sync again.

Studio 0.2 runs on marimo 0.25.0, so the sandbox image must provide that marimo
version. See
[Supported environment](../reference/compatibility.md#supported-environment).

To bring a new notebook into the hub, save the header in a local `notebook.py`
and choose that file under **Start from a file** in the **New Notebook** dialog.

### Choose a starter for hub storage

The **HTML document** starter keeps each view project to a few small files.
React, Svelte, Reveal.js slides, and Notebook Kit starters need
`marimo-studio[deno]>=0.2.2` and network access to the npm registry. Each of
those views also keeps its Deno build cache in `.artifacts/`, about 55 MB and
300 files for the React starter.

The hub saves at most 1,000 files and 100 MB per workspace and skips files past
that budget. Keep one Deno-based view per hub notebook so its source files stay
within the saved set.

## Create the first view

Open the notebook. The hub page shows the native marimo editor with an
**Add view** button in the Studio toolbar. Run the notebook's cells, click
**Add view**, keep the proposed name `dashboard`, choose **HTML document**, and
click **Create view**.

![The Add view dialog proposing dashboard with the HTML document starter selected](/screenshots/marimohub/add-view.png){width=450}

Notebook and Preview open side by side. Controls in Preview drive the same
kernel as the notebook, so moving a slider in the view reruns the dependent
cells and updates both panes.

View creation also rewrites the notebook header. It pins the installed Studio
version, for example `marimo-studio==0.2.2`, and records aliases for the cells
the starter placed. The hub saves those changes with `notebook.py`.

Continue with [Edit and preview in Studio](work-in-studio.md) and
[Place notebook results in a view](notebook-results.md) to shape the page.

## Check the saved view project

Stop the session from the hub's session menu when you finish. The hub saves
`notebook.py` and the workspace, and **Browse files** shows the view project:

```text
notebook.py
pyproject.toml
studio/
  dashboard/
    AGENTS.md
    index.html
    view.toml
```

![Browse files showing studio/dashboard/view.toml in the notebook workspace](/screenshots/marimohub/workspace-files.png)

The next session restores `studio/` into a fresh sandbox and opens Studio on the
`dashboard` view with its saved source.

## Run the view as an app

Choose **Open**, then **Run as app**. The hub starts the notebook with
`marimo run`, and Studio serves the default view at the app page.

![The dashboard view served as the notebook's marimohub app](/screenshots/marimohub/run-as-app.png)

[Run or export a view](run-and-share.md) covers runtimes and static export for
the same view outside the hub.

## Troubleshoot

| Symptom                                                          | Fix                                                                                                         |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| The notebook page shows the marimo editor with no Studio toolbar | Check that `dependencies` lists `marimo-studio`, then stop and restart the session                          |
| A new session offers **Add view** for a view you created         | Set `MARIMOHUB_PERSIST_WORKSPACE=workspace` and keep `view_root` outside `__marimo__/`                      |
| **Run as app** shows the notebook instead of the view            | Same fix. Run mode serves the notebook as a marimo app while the view root contains no view                 |
| A starter asks for `marimo-studio[deno]`                         | Change the dependency to `marimo-studio[deno]>=0.2.2` and restart the session                               |
| A view loses source files after a restart                        | Check the hub server log for `captureWorkspace` cap warnings and reduce the notebook to one Deno-based view |
