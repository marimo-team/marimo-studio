---
title: Work with several views
description: Give each audience its own page while reusing one Marimo notebook.
---

# Work with several views

One notebook can serve several named views. Each view has its own route,
frontend source, interactions, and publication.

```console
marimo-studio view create analysis.py --name dashboard
marimo-studio view create analysis.py --name report
```

The notebook's `[tool.marimo-studio]` table records the default view. Each view
directory records its provider in `view.toml`.

## Switch views

Use the view menu in Studio. Switching flushes pending source, prepares the
target preview, then commits the selected view and Source session together.
Rapid selections keep the newest request.

The selected notebook kernel stays active. Studio keeps a bounded prepared-frame
cache for each runtime. Up to three recent Server views stay warm, while
WebAssembly retains its selected view's worker frame. A warm Server switch
reuses the existing notebook session.

## Use different frontends

Each view can choose its own installed starter or extension for the audience:

```console
marimo-studio starter list
marimo-studio view create analysis.py --name report --starter STARTER
```

The notebook contract remains the same across views. A named cell, output, or
value target has one analytical meaning even when each page lays it out
differently.

## Build one view

```console
marimo-studio view build analysis.py --name report
```

Builds are view-local. A failed report build does not replace its last valid
page or affect another view.

## Choose the default

Set `default` in notebook metadata or project configuration:

```toml
[tool.marimo-studio]
default = "dashboard"
```

The default view is served at `/`. Other views use named routes.

## Remove a view

```console
marimo-studio view remove analysis.py --name report
```

Removal deletes the view directory after confirmation. It leaves Python
dependencies unchanged. A configured notebook keeps at least one view.

[Frontend authoring](authoring-options.md) covers custom source trees.
[Notebook results](notebook-results.md) covers the shared notebook contract.
