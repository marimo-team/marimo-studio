---
title: Configuration
description: Configure the notebook, default view, runtimes, aliases, view projects, provider options, and saved files.
---

# Configuration

Studio reads one `[tool.marimo-studio]` table from the notebook's
[PEP 723](https://peps.python.org/pep-0723/) block, which stores Python script
dependencies and tool configuration inside the script, or from a containing
`pyproject.toml`. The two forms are mutually exclusive for one notebook. When
both files configure the same notebook, Studio reports both paths and requires
one configuration source.

Both locations use [TOML](https://toml.io/en/), a configuration format built
from named tables and typed values.

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

| Field                   | Type                           | Default     | Behavior                                                                       |
| ----------------------- | ------------------------------ | ----------- | ------------------------------------------------------------------------------ |
| `default`               | string                         | Required    | Names the view served at `/`                                                   |
| `runtime`               | `"server"` or `"wasm"`         | `"server"`  | Chooses the notebook runtime when the URL has no valid override                |
| `runtimes`              | non-empty array of runtime IDs | `[runtime]` | Lists the distinct runtimes people may select. It must contain `runtime`       |
| `preserve_session`      | boolean                        | `false`     | Reconnects an eligible Python runtime refresh to its matching notebook session |
| `show_cell_logs`        | boolean                        | `true`      | Includes stdout and stderr in complete-cell projections                        |
| `cells`                 | table                          | Empty       | Stores stable aliases for existing notebook cells                              |
| `provider_dependencies` | array of requirements          | Omitted     | Inline PEP 723 ownership record for third-party requirements that Studio added |

For a standalone notebook, view creation pins the installed Studio version.
React and Svelte add the `deno` extra to that exact Studio requirement. An
installed third-party provider adds its exact distribution version to
`dependencies`.

Studio records each third-party requirement it introduced in
`provider_dependencies`. Static WebAssembly removes a still-owned exact
requirement from the browser notebook dependency list. A requirement remains
when it predates view creation, the user later changes it, or the notebook
imports the distribution directly.

`server` selects the Python runtime. `wasm` selects the Browser runtime. Runtime
selection and delivery are separate choices. `marimo run` serves a live
presentation. `marimo-studio view export` packages a static Browser runtime
site.

`preserve_session` applies to Python run-mode sessions. Studio reuses a session
when the saved notebook, public URL path, canonical public query, and replay
scope still match. A changed identity starts another session.

Studio caps the complete Browser runtime configuration at 16 MiB of UTF-8 JSON. A
`runtime-config-too-large` diagnostic means that record exceeded the boundary.
Notebook source and broad projection declarations are common contributors. Use
finite projection targets or reduce the saved notebook source before retrying.

See [Notebook result projections](projections.md) for runtime-visible result
contracts and [Limits](limits.md#runtime-payloads) for payload boundaries.

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

`notebook` is required in project configuration. It resolves relative to
`pyproject.toml` and must stay within that project directory. Project
configuration accepts the common fields in the notebook table and rejects
`provider_dependencies`. Add Studio and view provider requirements through the
project's dependency workflow.

## Provider environments

Python `dependencies` are the executable environment contract. For
`provider = "acme-views/report"`, the notebook or project must declare an active
`acme-views` dependency. `status`, `view create`, `view inspect`, `view read`,
`view write`, `view build`, `view export`, and `validate` resolve that metadata
before importing the provider.

Keep the `uv` executable available. Studio re-enters the target environment
through `uv` when the current process does not satisfy the resolved Studio and
provider requirements.

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

## View projects

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

A new Vanilla view creates `index.html` and `AGENTS.md` as editable Source
documents. Directly referenced local `style.css` and `main.js` files also enter
the Vanilla Source catalog. Other providers declare their own Source documents
and build inputs. See [Built-in view providers](built-in-providers.md) for the
initial project shapes and options.

`view.toml` records the view provider that inspects and builds the view project:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

A view provider can accept explicit options:

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "web/report.html"
```

`schema` must equal `1`. `provider` must be a valid installed provider key.
`options` must contain JSON-compatible TOML scalars, arrays, or tables with
finite numbers. Unknown top-level fields fail configuration loading.

Studio Source writes can update `options` and preserve the current provider
key. Create another view with the desired starter to change frontend stacks.
An external `view.toml` edit invalidates an in-flight Source mutation and
requires fresh provider inspection.

Studio maintains each view incarnation in `.owners/<view-name>.toml`. Keep the
`.owners` directory with the workspace. A valid project copied or renamed to a
new view name receives a fresh owner when Studio discovers it. Removing a view
through Studio records the absent name before that name can be reused.

Use Studio create and remove operations for same-name replacement. Existing
workspace and view handles reject the replacement through their observed
generations. [Identities and state](identities.md#ownership-generations)
defines those tokens.

The selected view provider validates `[options]` and reports unsupported values
beside `view.toml`.

View names start with a lowercase letter and contain lowercase letters, digits,
or hyphens. A name may use at most 240 UTF-8 bytes. Studio rejects reserved
route names and Windows device names. A directory becomes a view when it
contains a valid `view.toml`. Studio adopts an externally created view directory
by writing its owner record under the catalog lock.

## Source documents and build inputs

Provider inspection returns two separate allowlists:

| List             | Purpose                                                                     |
| ---------------- | --------------------------------------------------------------------------- |
| Source documents | Ordered UTF-8 files visible in Source with `edit` or `read` access          |
| Build inputs     | Exact files and bounded directories copied into an immutable build snapshot |

Studio adds editable `view.toml` to the Source catalog through its
provider-independent manifest path. View providers include that file in the
build input set and keep it out of their `editor_documents` records.

A Source path uses forward slashes, starts at the view project root, and cannot
contain `.` or `..` segments. It must name a contained regular file. Source
writes reject symlinks, invalid UTF-8, files larger than
64 MiB, read-only documents, stale revisions, and stale workspace or view
generations.

## Build profiles

`development` and `production` maintain independent build attempts and retained
artifacts:

| Profile       | Used by                                 |
| ------------- | --------------------------------------- |
| `development` | Studio Preview and authoring inspection |
| `production`  | Run mode and static export              |

A failed replacement keeps the last successful artifact for the same profile
available. See [Identities and state](identities.md#build-freshness) for the
authoring status values.

## Saved and generated files

Commit `.owners/`, `view.toml`, Source documents, build inputs, frontend
configuration, and dependency lockfiles. Studio writes replaceable build state
beneath each view's `.artifacts/` directory and cross-process locks beneath the
workspace `.locks/` directory. The workspace `.gitignore` excludes both
generated paths.

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
