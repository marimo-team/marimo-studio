---
title: Configuration
description: Configure server entry, embedding, the notebook, default view, runtimes, aliases, view projects, provider options, and saved files.
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

## Edit root ownership

Studio opens at edit-mode `/` by default. An embedding host can keep the native
marimo editor at `/` and expose Studio through `/studio/`:

```console
MARIMO_STUDIO_EDIT_ROOT=marimo marimo edit analysis.py --headless
```

`MARIMO_STUDIO_EDIT_ROOT` accepts two values:

| Value    | Edit `/`                  | Edit `/studio/`            | Run `/`                     |
| -------- | ------------------------- | -------------------------- | --------------------------- |
| `studio` | Studio entry, the default | Studio authoring workspace | Default Studio presentation |
| `marimo` | Native marimo editor      | Studio authoring workspace | Default Studio presentation |

The setting is process configuration. Apply it before marimo loads the Studio
server extension. A direct `/studio/` request can create the first view, then
opens Source, Preview, and the embedded native editor.

Opening `/studio/` creates a Studio browser client bound to a native marimo
connection. Tabs editing the same notebook share its Python kernel through
marimo's editor and interactor roles. Enter Studio before calling `view.show()`
from code mode. A remote agent can select a connected Studio browser client.
Navigating between `/` and `/studio/` creates a connection to the same kernel
while marimo retains the notebook session. See
[Navigate and preserve state](../guide/navigation-and-sessions.md#open-multiple-tabs)
for shared state and runtime boundaries.

Authentication, public base paths, WebSockets, and framing remain server and
reverse-proxy concerns. A host must forward the complete configured marimo base
path, including `/studio/`, `/_marimo-studio/`, named views, revision-qualified
artifacts, native HTTP routes, and WebSockets. Its framing policy must admit the
outer host, the Studio document, and Studio's nested native editor.

## Notebook settings

Creating the first view can add these settings to a standalone notebook:

```python
# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = ["marimo-studio"]
#
# [tool.marimo-studio]
# default = "dashboard"
# ///
```

| Field                   | Type                           | Default                                   | Behavior                                                                       |
| ----------------------- | ------------------------------ | ----------------------------------------- | ------------------------------------------------------------------------------ |
| `default`               | string                         | Required                                  | Selects the initial Studio workspace view and the view served at run-mode `/`  |
| `runtime`               | `"server"` or `"wasm"`         | `"server"`                                | Chooses the notebook runtime when the URL has no valid override                |
| `runtimes`              | non-empty array of runtime IDs | `[runtime]`                               | Lists the distinct runtimes people may select. It must contain `runtime`       |
| `preserve_session`      | boolean                        | `false`                                   | Reconnects an eligible Python runtime refresh to its matching notebook session |
| `show_cell_logs`        | boolean                        | `true`                                    | Includes stdout and stderr in complete-cell projections                        |
| `view_root`             | relative path                  | See [Project settings](#project-settings) | Stores authored view projects at a configurable location                       |
| `cells`                 | table                          | Empty                                     | Stores stable aliases for existing notebook cells                              |
| `provider_dependencies` | array of requirements          | Omitted                                   | Inline PEP 723 ownership record for third-party requirements that Studio added |

For a standalone notebook, view creation pins the installed Studio version.
React, Svelte, and Notebook Kit add the `deno` extra to that exact Studio requirement. An
installed third-party provider adds its exact distribution version to
`dependencies`.

Studio records each third-party requirement it introduced in
`provider_dependencies`. Static WebAssembly removes a still-owned exact
requirement from the browser notebook dependency list. A requirement remains
when it predates view creation, the user later changes it, or the notebook
imports the distribution directly.

`server` selects the Python runtime. `wasm` selects the Browser runtime. Add
`zero-python` to `runtimes` to preview prepared states in the Studio editor.
`runtime` must remain `server` or `wasm` because it also governs `marimo run`.
`marimo-studio view export` uses the Prepared runtime by default and accepts
`--runtime wasm` for a static Browser runtime site.

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
dependencies = ["marimo-studio"]

[tool.marimo-studio]
notebook = "analysis.py"
view_root = "studio"
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm"]
```

`notebook` is required in project configuration. It resolves relative to
`pyproject.toml` and must stay within that project directory. Project
configuration accepts the common fields in the notebook table and rejects
`provider_dependencies`. Add Studio and view provider requirements through the
project's dependency workflow.

`view_root` is optional. It is a portable relative path resolved from the file
that contains `[tool.marimo-studio]`. When omitted, Studio stores views at
`__marimo__/studio/<notebook-stem>/` beside the notebook. Set it when the host
or deployment treats `__marimo__/` as generated runtime state and persists
authored project files from another workspace directory.

## Process settings

`MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS` controls which cross-origin parent
documents may frame the Studio edit workspace. Pass a comma-separated list of
exact HTTP or HTTPS origins. When the variable is unset or empty, Studio keeps
the Content Security Policy `frame-ancestors` directive at `'self'`.

Studio accepts at most 32 origin entries and 4,096 UTF-8 bytes. It normalizes
host casing, default ports, and an optional trailing slash, then removes
duplicates. An invalid or oversized value stops server startup.

This setting changes framing policy. It does not grant request access or bypass
marimo authentication. Allow only parent origins whose pages you trust to
present Studio controls. See [Embed the Studio edit
workspace](../guide/deploy.md#embed-the-studio-edit-workspace) for the deployment
command and clickjacking boundary.

Studio also preserves marimo's trusted, server-level `html_head` content in its
outer edit document. A host-injected script can declare its exact parent with a
`data-parent-origin` attribute. Studio validates that HTTP or HTTPS origin and
adds it to the edit document's framing policy. Explicit
`MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS` entries remain additive.

## Provider environments

Python `dependencies` are the executable environment contract. For
`provider = "acme-views/report"`, the notebook or project must declare an active
`acme-views` dependency. `status`, `view create`, `view inspect`, `view read`,
`view write`, `view build`, `view preflight`, `view export`, and `validate`
resolve that metadata before importing the provider.

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

By default, views for `analysis.py` live beside the notebook:

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

`schema` must equal `1`. Loading the manifest validates `provider` as a
canonical provider key. Inspection, build, and authoring operations require a
matching installed provider registration. `options` must contain
JSON-compatible TOML scalars, arrays, or tables with finite numbers. Unknown
top-level fields fail configuration loading.

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

## Prepared state space

A view project can declare its finite input state space in `states.yaml`.
The file uses `marimo-export`'s public `StateSpace` contract. Zero-Python export
executes those states and packages the projected results:

```yaml
schema: marimo-export.states.v1
default_state: matrix-000000
matrix:
  threshold: [0.25, 0.5, 0.75]
```

`states` maps stable state names to complete or sparse input mappings. `matrix`
maps each input to a non-empty array of accepted frontend values and expands
their Cartesian product into `matrix-000000`, `matrix-000001`, and subsequent
states. `default_state` must name one expanded or explicit state.

The state space accepts portable JSON values, rejects duplicate keys and YAML
aliases, and caps the expanded set at 10,000 states. A view with no
`states.yaml` prepares its current baseline. Controls in a prepared static view
can select the states present in that publication.

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

The browser Source panel lists the provider's `editor_documents`. Python
`View.inspect()` and CLI `view inspect` prepend editable `view.toml` through
Studio's provider-independent manifest path. View providers include that file
in the build input set and keep it out of their `editor_documents` records.

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

The notebook filename stem must fit one portable cross-platform filename. With
the default view root, it also determines the view directory. Rename both in
the same change:

```console
mv analysis.py revenue.py
mv __marimo__/studio/analysis __marimo__/studio/revenue
```

When `view_root` is configured, rename the notebook and keep the configured
view directory unchanged.

For project settings, update `tool.marimo-studio.notebook` as part of that
change.
