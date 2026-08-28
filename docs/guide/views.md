---
title: Create pages for different audiences
description: Reuse one notebook across pages with different explanations, layouts, and interactions.
---

# Create pages for different audiences

A team dashboard and a public report can share the same notebook while
presenting its results differently. Create one named page for each job:

```console
marimo-studio view create dashboard --target analysis.py
marimo-studio view create report --target analysis.py
```

Studio calls each named page a **view**. Both views read the same notebook
results. Their HTML, styles, wording, and browser interactions remain separate.

## Switch pages while you work

Use the page menu in Studio to move between `dashboard` and `report`. Studio
saves pending Source edits before changing the selected page. The notebook
session stays active, so controls and computed results remain available.

Each page builds independently. A failed report build leaves its last
successful version available and does not change the dashboard.

## Choose the page at the main URL

The default view opens at `/`. Set it in the notebook configuration:

```toml
[tool.marimo-studio]
default = "dashboard"
```

Other views use their names as routes. A view named `report` opens at
`/report/`.

## Remove a page

```console
marimo-studio view remove report --target analysis.py
```

Studio confirms before deleting the page and its source files. When you remove
the default view, the confirmation names the view that will open at `/`
afterward. A configured notebook always keeps at least one view.

Use [HTML, React, or Svelte](frontend-options.md) when the pages need different
frontend structures. Use [notebook results](notebook-results.md) to keep their
analytical meaning aligned.
