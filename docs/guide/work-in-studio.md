---
title: Edit and preview in Studio
description: Work with notebook code, view source, and the rendered result in one Marimo session.
---

# Edit and preview in Studio

Open Marimo in an environment containing Studio:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

The thin Studio toolbar appears immediately, including in a new, unsaved
notebook. Click **Add view** to name a view and choose a starter. For an
unsaved notebook, the action first opens Marimo's Save dialog. Studio writes
view configuration when you create the view.

## Work beside the notebook

Studio opens the notebook and custom view side by side. The native agent
sidebar remains available, including when you focus the custom view.

- **Show notebook only** focuses the notebook. Click **Show view beside notebook**
  to restore the split, including its Source pane and sizes.
- **Edit view source** opens Source beneath the custom view. File tabs select
  the view's authored documents.
- **Live** (or the current status) gives a short runtime state. Hover or focus it
  for a contextual summary. Click it for diagnostics and runtime choices.
- **Workspace options** contains focus commands and **Open preview in new tab**.

## Arrange the workspace

Drag a divider to resize. Choose **Arrange panes** from **Workspace options**
to expose each pane's placement, swap, and close controls. Pane headers remain
hidden during normal editing. The menu also offers equal split sizes and the
saved or default layout.

Studio saves the custom layout for each notebook and selected view in the
current browser. **Open saved layout** returns to that arrangement.

When the available width or height cannot fit the panes, use the **Visible
surface** selector to choose Notebook, Source, or Preview.

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

Click the status item in the toolbar to choose where notebook code executes:

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
