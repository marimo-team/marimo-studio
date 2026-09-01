---
title: Configuration
description: Configure the notebook, default view, execution environments, aliases, view source, and generated files.
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
# requires-python = ">=3.10,<3.15"
# dependencies = ["marimo-studio==0.1.0"]
#
# [tool.marimo-studio]
# default = "dashboard"
# ///
```

| Field                   | Default     | Behavior                                                            |
| ----------------------- | ----------- | ------------------------------------------------------------------- |
| `default`               | Required    | Names the view served at `/`                                        |
| `runtime`               | `"server"`  | Chooses where the notebook runs when the URL has no override        |
| `runtimes`              | `[runtime]` | Lists the runtimes people may select                                |
| `preserve_session`      | `false`     | Reconnects a Python-backed refresh to its matching notebook session |
| `show_cell_logs`        | `true`      | Includes stdout and stderr in complete-cell results                 |
| `cells`                 | Empty       | Stores aliases for existing anonymous cells                         |
| `provider_dependencies` | Omitted     | Records third-party requirements that Studio added                  |

For a standalone notebook, view creation pins the installed Studio version.
React and Svelte add the `deno` extra to that exact Studio requirement. An
installed third-party provider adds its exact distribution version to
`dependencies`.

Studio records each third-party requirement it introduced in
`provider_dependencies`. Static WebAssembly removes a still-owned exact
requirement from the browser notebook dependency list. A requirement remains
when it predates view creation, the user later changes it, or the notebook
imports the distribution directly.

`runtime` accepts `server` for Python execution and `wasm` for browser
execution. The default runtime must also appear in `runtimes`.

Studio caps the complete browser runtime payload at 16 MiB of UTF-8 JSON. A
`runtime-config-too-large` diagnostic means that record exceeded the boundary.
Notebook source and broad projection declarations are common contributors. Use
finite projection targets or reduce the saved notebook source before retrying.

Runtime and delivery are separate choices. These fields choose where the
notebook executes. Use `marimo run` to serve a live view and
`marimo-studio view export` to package the Browser runtime as a static directory.

## Project settings

A Python project can keep the same settings in `pyproject.toml`:

```toml
[project]
name = "analysis"
version = "0.1.0"
dependencies = ["marimo-studio==0.1.0"]

[tool.marimo-studio]
notebook = "analysis.py"
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm"]
```

`notebook` resolves relative to `pyproject.toml` and must stay within that
project directory. Add Studio and any frontend build dependencies through the
project's package workflow.

## Provider environments

`dependencies` is the executable environment contract. For
`provider = "acme-views/report"`, the notebook or project must declare an active
`acme-views` dependency. `status`, `view create`, `view inspect`, `view read`,
`view write`, `view build`, `view export`, and `validate` resolve that metadata
before importing the provider.

`provider_dependencies` records the exact entries Studio introduced. Static
WebAssembly cleanup uses that ownership record when removing an owned provider
requirement.

When a Studio or provider requirement has an environment marker, Studio
evaluates it against the interpreter that starts the command. Mutually exclusive
markers select one active branch. An inactive branch contributes neither its
extras nor its direct source. Start the CLI with a Python version accepted by
the notebook and project `requires-python` constraints.

Active declarations for one distribution must select one coherent source and
version. Compatible ranges may accompany one exact pin. Studio rejects
conflicting exact pins, different direct URLs, a direct URL combined with a
version range, and multiple differing ranges with no exact selection. Pin the
provider or align those ranges before retrying.

## View settings and source

Views for `analysis.py` live beside the notebook:

```text
__marimo__/studio/analysis/
  .gitignore
  .owners/
    dashboard.toml
  dashboard/
    view.toml
    index.html
    style.css
    main.js
```

The default starter creates `index.html`. The optional `style.css` and `main.js`
files appear when that document references them directly. Other providers can
declare a different source tree.

`view.toml` records the installed frontend integration that creates and builds
the view:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

An integration can accept explicit view settings:

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "web/report.html"
```

Studio maintains each view incarnation in `.owners/<view-name>.toml`. Keep the
`.owners` directory with the workspace. A valid project copied or renamed to a
new view name receives a fresh owner when Studio discovers it. Removing a view
through Studio records the absent name before that name can be reused.

Use Studio create and remove operations for same-name replacement. Studio can
also rotate ownership after it observes an external absence. A filesystem
delete and recreation completed between observations is outside the mutation
contract when it reuses the same directory owner. This includes exact-byte
recreation.

The selected integration validates `[options]` and reports unsupported values
beside the file.

View names start with a lowercase letter and contain lowercase letters, numbers,
or hyphens. They must also fit one portable cross-platform filename. A directory
becomes a view when it contains a valid `view.toml`. Studio adopts an externally
created view directory by writing its owner record under the catalog lock.

## Saved and generated files

Commit `.owners/`, `view.toml`, view source, frontend configuration, and
dependency lock files. Studio writes replaceable build output beneath each
view's `.artifacts/` directory and cross-process locks beneath the workspace
`.locks/` directory. The workspace `.gitignore` excludes both generated paths.

Delete one view's `.artifacts/` directory when its generated state needs a
clean rebuild. The next build recreates it from saved source.

## Cell aliases

Native marimo cell names resolve directly. Give an existing anonymous cell a
stable name when view source needs to reference it:

```console
marimo-studio notebook bind summary --target analysis.py --cell 12
```

Studio stores aliases under `[tool.marimo-studio.cells]` and makes them
available to every view. View creation adds collision-free aliases for
anonymous cells placed by the selected starter.

## Rename a notebook

The notebook filename stem must fit one portable cross-platform filename. It
also determines the view directory. Rename both in the same change:

```console
mv analysis.py revenue.py
mv __marimo__/studio/analysis __marimo__/studio/revenue
```

For project settings, update `tool.marimo-studio.notebook` as part of that
change.
