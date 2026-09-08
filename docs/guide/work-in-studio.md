---
title: Edit and preview in Studio
description: Work with notebook code, view source, and the rendered result in one Marimo session.
---

# Edit and preview in Studio

Open the notebook with the launch requirements printed by `view create`. For a
notebook that uses the default Vanilla starter:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Studio connects three surfaces to the saved notebook:

- **Notebook** edits Python and reactive computation.
- **Source** edits the selected view project's source documents.
- **Preview** renders the current artifact with notebook results attached.

## Choose a mode

| Mode         | Surfaces             |
| ------------ | -------------------- |
| **Notebook** | Notebook             |
| **Develop**  | Notebook and Preview |
| **Preview**  | Preview              |
| **Source**   | Source and Preview   |

Studio opens in **Develop**, with Notebook and Preview sharing the page equally.
Click **Source** in the toolbar to open the view editor beneath Notebook. Preview
keeps its full height. Click **Source** again to close the editor.

Choose **Source** from **Workspace options** to focus on Source and Preview.

## Arrange the workspace

Use **Arrange** in a pane header to place it above, below, or beside another
pane, swap panes, add a missing surface, or close the pane. Drag a divider to
resize. Open **Workspace options** to equalize split sizes, restore the default
workspace, or open the saved layout.

Studio saves the custom layout for each notebook and selected view in the
current browser. **Open saved layout** returns to that arrangement.

When the available width or height cannot fit every visible pane, Studio uses
compact navigation. Choose Notebook, Source, or Preview from the compact tabs
instead of shrinking the surfaces below their working size.

## Save and build

Source saves the active document and rebuilds the selected view. The build
status reports:

- **Building** while a replacement artifact is being prepared
- **Up to date** when Preview matches saved source
- **Build needed** when saved source has changed
- **Build failed** when the latest attempt reported an error

Preview stays on the last successful artifact while another build runs. A
failed build keeps that artifact visible and puts the repair diagnostic beside
Source.

Use an explicit build after another editor, coding agent, or CI process changes
the project:

```console
marimo-studio view build dashboard --target analysis.py
```

## Switch views and runtimes

The view menu saves pending Source edits before selecting another view. A
failed save or unresolved conflict stops the switch so the current document can
be repaired.

The runtime menu controls where notebook code executes:

- **Python runtime** uses the editor's Python session and can access local
  files, databases, installed packages, and server credentials. Its
  configuration ID is `server`.
- **Browser runtime** starts a notebook in a browser worker. The browser
  receives notebook source and must reach its dependencies and data. Its
  configuration ID is `wasm`.

Switching runtimes keeps the view artifact fixed and replaces the notebook
runtime that supplies results.

Use **Open preview in new tab** to inspect the current presentation without the
authoring panes. Continue with [Manage view source](manage-source.md) for the
Source catalog and conflict recovery.
