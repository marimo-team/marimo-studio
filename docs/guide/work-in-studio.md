---
title: Edit and preview in Studio
description: Work with notebook code, page source, and the rendered result in one marimo session.
---

# Edit and preview in Studio

Open a notebook that already has a page:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Studio keeps three surfaces connected to the same saved notebook:

- **Notebook** contains Python and reactive computation.
- **Source** contains the selected page's frontend files.
- **Preview** renders the page with notebook results attached.

Choose **Develop** to arrange all three for everyday authoring. Notebook,
Source, and Preview can also fill the workspace individually.

## Save and rebuild

Source saves after an edit and rebuilds the selected page. The build status
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

## Switch pages

The page menu saves pending edits before selecting another view. A failed save
or unresolved conflict stops the switch. The previous page remains active so
you can repair the source and retry.

## Compare Python and browser execution

The runtime menu answers where the notebook runs:

- **Python** uses the editor's Python session and can access local files,
  databases, installed packages, and server credentials.
- **Browser** starts a separate notebook in the visitor's browser. The browser
  receives the notebook source and must be able to fetch its data.

Switching the runtime keeps the page source fixed while changing where notebook
code and controls execute.

Use [Run or publish a page](run-and-share.md) before exposing either runtime to
an audience.
