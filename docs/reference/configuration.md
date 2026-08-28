---
title: Configuration
description: Configure the notebook, default page, execution environments, aliases, page source, and generated files.
---

# Configuration

Studio reads settings from the notebook's PEP 723 block or from one project
`pyproject.toml`. Keep one source of Studio settings for each notebook. When
both files configure the same notebook, Studio reports both paths and asks you
to choose one.

## Notebook settings

Creating the first view can add these settings to a standalone notebook:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
#
# [tool.marimo-studio]
# default = "dashboard"
# ///
```

| Field              | Default     | Behavior                                                            |
| ------------------ | ----------- | ------------------------------------------------------------------- |
| `default`          | Required    | Names the view served at `/`                                        |
| `runtime`          | `"server"`  | Chooses where the notebook runs when the URL has no override        |
| `runtimes`         | `[runtime]` | Lists the runtimes people may select                                |
| `preserve_session` | `false`     | Reconnects a Python-backed refresh to its matching notebook session |
| `show_cell_logs`   | `true`      | Includes stdout and stderr in complete-cell results                 |
| `cells`            | Empty       | Stores aliases for existing anonymous cells                         |

`runtime` accepts `server` for Python execution and `wasm` for browser
execution. The default runtime must also appear in `runtimes`.

## Project settings

A Python project can keep the same settings in `pyproject.toml`:

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
```

`notebook` resolves relative to `pyproject.toml`. Add Studio and any frontend
build dependencies through the project's package workflow.

## View settings and source

Views for `analysis.py` live beside the notebook:

```text
__marimo__/studio/analysis/
  .gitignore
  dashboard/
    view.toml
    index.html
```

`view.toml` records the installed frontend integration that creates and builds
the page:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

An integration can accept explicit page settings:

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "web/report.html"
```

Studio writes `view.toml`. The selected integration validates `[options]` and
reports unsupported values beside the file.

View names start with a lowercase letter and contain lowercase letters,
numbers, or hyphens. A directory becomes a view when it contains a valid
`view.toml`.

## Saved and generated files

Commit `view.toml`, page source, frontend configuration, and dependency lock
files. Studio writes replaceable build output beneath each view's `.artifacts/`
directory and cross-process locks beneath the workspace `.locks/` directory.
The workspace `.gitignore` excludes both generated paths.

Delete one view's `.artifacts/` directory when its generated state needs a
clean rebuild. The next build recreates it from saved source.

## Cell aliases

Native marimo cell names resolve directly. Give an existing anonymous cell a
stable name when page source needs to reference it:

```console
marimo-studio notebook bind summary --target analysis.py --cell 12
```

Studio stores aliases under `[tool.marimo-studio.cells]` and makes them
available to every view.

## Rename a notebook

The notebook filename determines its view directory. Rename both in the same
change:

```console
mv analysis.py revenue.py
mv __marimo__/studio/analysis __marimo__/studio/revenue
```

For project settings, update `tool.marimo-studio.notebook` as part of that
change.
