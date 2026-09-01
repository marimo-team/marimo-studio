---
title: Edit and preview in Studio
description: Work with notebook code, view source, and the rendered result in one marimo session.
---

# Edit and preview in Studio

Use the exact launch requirements printed by `view create`. For a notebook with
the default 0.1.0 view, run:

```console
uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox
```

Studio keeps three surfaces connected to the same saved notebook:

- **Notebook** contains Python and reactive computation.
- **Source** contains the selected view's frontend files.
- **Preview** renders the view with notebook results attached.

Choose **Develop** to arrange all three for everyday authoring. Notebook,
Source, and Preview can also fill the workspace individually.

## Save and rebuild

Source saves after an edit and rebuilds the selected view. The build status
shows **Building**, **Up to date**, **Build needed**, or **Build failed**.

Preview stays on the last successful version while another build runs. A failed
build keeps that version visible and places the repair message beside Source.

Use an explicit terminal build when another editor, a coding agent, CI, or a
production workflow changes the files:

```console
marimo-studio view build dashboard --target analysis.py
```

## Resolve a concurrent edit

Studio compares each save with the source version that was loaded. When another
browser, editor, or coding agent saves first, Studio keeps your unsaved buffer
and shows both versions.

- **Use saved version** discards your unsaved edits and loads the newer file.
- **Overwrite saved version with my edits** replaces the newer saved file with
  your buffer.

Review **Your edits** and **Saved version** before choosing. When Studio reports
a recovery file, that path contains the previous saved content.

## Switch views

The view menu saves pending edits before selecting another view. A failed save
or unresolved conflict stops the switch. The previous view remains active so
you can repair the source and retry.

## Compare Python and browser execution

The runtime menu answers where the notebook runs:

- **Python** uses the editor's Python session and can access local files,
  databases, installed packages, and server credentials.
- **Browser** starts a separate notebook in the visitor's browser. The browser
  receives the notebook source and must be able to fetch its data.

Switching the runtime keeps the view source fixed while changing where notebook
code and controls execute.

Use [Run or publish a view](run-and-share.md) before sharing either runtime.
