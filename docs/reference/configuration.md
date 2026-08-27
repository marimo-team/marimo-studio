---
title: Notebook configuration
description: Configure a Studio notebook, its default view, runtimes, logs, and cell aliases.
---

# Notebook configuration

Studio stores notebook settings in PEP 723 metadata or in a project
`pyproject.toml`. Each view keeps one small `view.toml` beside its frontend
source.

## Notebook metadata

Creating the first view adds the package dependency and Studio table:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
#
# [tool.marimo-studio]
# default = "dashboard"
# ///
```

| Field              | Default     | Behavior                                           |
| ------------------ | ----------- | -------------------------------------------------- |
| `default`          | Required    | Selects the view served at `/`                     |
| `runtime`          | `"server"`  | Selects the runtime when a URL has no override     |
| `runtimes`         | `[runtime]` | Permits runtimes in Studio and run mode            |
| `preserve_session` | `false`     | Reconnects a Server refresh with a matching query  |
| `show_cell_logs`   | `true`      | Includes stdout and stderr in complete-cell mounts |
| `cells`            | Empty       | Stores optional aliases shared by every view       |

`preserve_session` reuses a run-mode Server kernel when the canonical public
notebook query matches the query that created it. Private Studio routing and
transport keys do not affect the match. A different public query starts a fresh
kernel and presentation.

Install frontend extensions through normal Python dependencies. For a
notebook-local PEP 723 configuration, Studio adds the selected starter's
requirement when it creates the view. Project dependencies follow the
project's package workflow. Removing a view leaves dependencies unchanged.

## Project configuration

A managed project can use `pyproject.toml`:

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

`notebook` resolves relative to `pyproject.toml`.

## View manifest

Each view selects one installed frontend extension:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

The manifest stores explicit overrides:

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "web/report.html"
```

Studio passes explicit option values to provider inspection and build. The
provider reports diagnostics for unsupported keys or values. Starter identity
is creation-time information and is not stored in the project.

Views for `analysis.py` live at:

```text
__marimo__/studio/analysis/<view-name>/
```

A directory is a view when it has a valid `view.toml`. View names start with a
lowercase letter and contain lowercase letters, numbers, or hyphens.

Commit `view.toml` and the frontend source beneath this directory. Generated
`.artifacts/` directories and the workspace `.locks/` directory remain ignored.

The notebook stem selects the workspace directory. Rename a notebook and its
authored workspace together:

```console
mv analysis.py revenue.py
mv __marimo__/studio/analysis __marimo__/studio/revenue
```

For project configuration, update `tool.marimo-studio.notebook` in the same
change.

## Cell aliases

Native Marimo cell names resolve directly. Bind an anonymous cell when it needs
a stable target:

```console
marimo-studio notebook bind summary --target analysis.py --cell 12
```

Aliases are stored under `[tool.marimo-studio.cells]`. Use native cell names
for new view-facing results when possible.

[View projects](view-project.md) defines source and generated files.
[Runtimes](runtimes.md) defines server and WebAssembly behavior.
