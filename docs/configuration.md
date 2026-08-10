---
title: Notebook configuration
description: Configure Studio views, runtimes, session refreshes, projected logs, and cell aliases.
---

# Notebook configuration

Studio reads configuration from the notebook's PEP 723 metadata or from a
project `pyproject.toml`. Use `marimo-studio view add` to create the initial
configuration and `marimo-studio bind` to manage cell aliases.

Configuration defines a Studio workspace before view source exists. Opening a
configured notebook in `marimo edit` presents an authenticated initializer when
the view directory is empty. The initializer creates the configured `default`
view and opens its authoring workspace.

## Configure one notebook

`view add` stores notebook-local settings in the PEP 723 block:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
# runtime = "server"
# runtimes = ["server", "wasm"]
# preserve_session = false
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# summary = { ref = "cell:v1:<semantic-sha256>:<layout-sha256>:0" }
# ///
```

| Field              | Type     | Default     | Behavior                                                               |
| ------------------ | -------- | ----------- | ---------------------------------------------------------------------- |
| `default`          | String   | Required    | Select the view served at `/`                                          |
| `runtime`          | String   | `"server"`  | Select the runtime when a view URL has no override                     |
| `runtimes`         | String[] | `[runtime]` | Permit runtimes in run mode                                            |
| `preserve_session` | Boolean  | `false`     | Reconnect a manual server-runtime refresh to its current kernel        |
| `show_cell_logs`   | Boolean  | `true`      | Render cell standard output and standard error in projected cell hosts |
| `cells`            | Table    | Empty       | Store aliases shared by every view                                     |

`runtime` must appear in `runtimes`. Runtime IDs follow the same lowercase
letters, numbers, and hyphens pattern as view names.

Set `show_cell_logs = false` when a projected page should exclude text written
through `print`, Python logging, and warnings. Primary cell results, media,
input prompts, and structured Marimo errors continue to render.

Set `preserve_session = true` when a manual refresh of a server-runtime page
should return the browser to its current run-mode kernel. The serving Marimo
process must still retain that session, and reconnecting requests must reach
the same process.

## Configure a project

A managed project can place the same settings in `pyproject.toml`:

```toml
[project]
name = "analysis"
version = "0.1.0"
dependencies = ["marimo-studio"]

[tool.marimo-studio]
notebook = "analysis.py"
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm"]
preserve_session = false
show_cell_logs = false

[tool.marimo-studio.cells]
summary = { ref = "cell:v1:<semantic-sha256>:<layout-sha256>:0" }
```

`notebook` is required in project configuration and resolves relative to
`pyproject.toml`. View files still live beside that notebook under
`__marimo__/studio/`.

## Resolve a target

When a command receives a notebook path, Studio checks:

1. PEP 723 metadata in that notebook.
2. The nearest parent `pyproject.toml` whose `notebook` field resolves to it.

Notebook metadata wins when both sources identify the same notebook. A
conflict reports both configured paths.

When a command receives a directory or no target, Studio looks for one
configured notebook in that directory and for project configuration in its
parent chain. Pass the notebook path when a directory contains more than one
configured notebook.

## Locate view source

Views for `analysis.py` live at:

```text
__marimo__/studio/analysis/<view-name>/
```

Every immediate child directory with an `index.html` is a view. The directory
name is also its run-mode route.

Studio reports a configured notebook with zero views as `needs-view`. A
workspace becomes `ready` when at least one view exists and `default` names one
of those views.

The default starter files are:

```text
index.html
app.css
```

Add JavaScript modules, images, fonts, and nested asset directories beside
them. Relative URLs resolve from the authored file that references them.

## Manage cell aliases

The `cells` table maps an alias to a stable cell reference. Create and update
these entries through the CLI:

```console
uvx marimo-studio bind analysis.py --cell 12 --as summary
```

Native Marimo cell names require no alias. During an active `marimo edit`
session, a configured alias follows its cell as the cell moves or its Python
meaning changes. Edits made while the notebook is closed resolve across
formatting and comment changes. Reinspect and bind with `--overwrite` when an
offline edit changes the cell's meaning or makes the match ambiguous. Deleting
a cell removes its configured aliases when the notebook is saved.

[CLI reference](cli.md) defines command output and exit codes. [Run and share
views](share-views.md) explains how runtime settings affect deployment.
