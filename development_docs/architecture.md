# Architecture

Marimo Studio runs inside Marimo. Marimo owns the process, authentication,
notebook execution, sessions, WebSockets, virtual files, and native routes.
Studio adds authored view documents, projection routes, runtime adapters, and
an editor workspace around those services.

```text
Marimo process
  -> Studio middleware and kernel extension
     -> Python workspace and server services
        -> validated browser records
           -> Studio workspace or custom view document
```

## Python responsibilities

| Owner                                                                 | Responsibility                                                           |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Marimo                                                                | ASGI lifecycle, auth, sessions, kernels, native APIs, and virtual files  |
| `_entrypoints`                                                        | Register Studio middleware and the kernel lifespan extension             |
| `_workspace`                                                          | Resolve configuration, targets, aliases, views, checks, and source files |
| `app.py`, `checks.py`, `environment.py`, `inspect.py`, `workspace.py` | Compose workspace rules with Marimo adapters at public boundaries        |
| `_compat`                                                             | Translate private Marimo APIs into Studio-owned records                  |
| `_server`                                                             | Translate authenticated HTTP requests into Studio services               |
| `export.py`                                                           | Package one resolved view as a static WebAssembly site                   |
| `_cli`                                                                | Adapt Click commands and output formats to application services          |

`_workspace` accepts `NotebookInspector` and `RuntimeProber` ports when a
rule needs notebook data. It imports no compatibility adapter. `_cli` also
stays independent of `_compat`. Public services, `_server`, and extension
entry points are composition boundaries that connect those slices.

Private imports beginning with `marimo._` stay in `_compat`. Ruff enforces the
boundary. Compatibility code converts Marimo sessions, graph state, requests,
and kernel messages into records owned by `marimo_studio.types` or
`_workspace`.

## Browser responsibilities

| Owner                      | Responsibility                                                         |
| -------------------------- | ---------------------------------------------------------------------- |
| `packages/protocol`        | Zod schemas and inferred types for browser and server records          |
| `packages/runtime`         | Runtime registry, mount contract, session update, and disposal         |
| `packages/presentation`    | Custom document lifecycle, projections, runtime mount, and view styles |
| `packages/studio`          | Editor workspace, source editors, views, layouts, and preview control  |
| `packages/marimo-frontend` | Named adapters around Marimo's unstable frontend surface               |
| `apps/browser`             | Compose runtime and Studio entry points into packaged browser assets   |
| `apps/e2e`                 | Exercise live behavior across the editor, kernel, files, and previews  |

Browser dependencies point toward contracts:

```text
apps/browser
  |-> presentation -> runtime -> protocol
  |       |-> protocol
  |       `-> marimo-frontend
  `-> studio -> protocol
```

`packages/protocol` performs no network, filesystem, DOM, or window I/O.
`packages/runtime` performs no Marimo, React, or browser I/O.
`packages/studio` stays independent of presentation and Marimo frontend code.
Root `vite.config.ts` enforces these package boundaries and the internal
`app -> features -> shared` direction in Studio.

## Activation

The Python distribution registers two Marimo entry points:

```toml
[project.entry-points."marimo.server.asgi.middleware"]
marimo-studio = "marimo_studio._entrypoints:server_middleware"

[project.entry-points."marimo.kernel.lifespan"]
marimo-studio = "marimo_studio._entrypoints:kernel_lifespan"
```

The middleware resolves notebook configuration from PEP 723 metadata or the
nearest matching `pyproject.toml`. Configured view files live under
`__marimo__/studio/<notebook-stem>/<view>/`. Requests for another notebook
continue through Marimo.

The kernel extension registers value reads for configured notebooks. A view
can read only the cell aliases and value selectors present in its resolved
document. Requests travel through Marimo's kernel queue.

## Edit and run sessions

Edit mode serves the workspace at `/studio/<view>/`. The workspace keeps the
native editor and one frame per available preview runtime mounted while the
layout, selected view, or visible runtime changes. It prepares the selected
runtime and the WebAssembly preview in the background.

The Server preview joins the editor's Marimo session as a kiosk consumer after
the editor session exists. It reuses that kernel's outputs, native controls,
and anywidget models. Marimo relays accepted native control writes to peer
consumers in the session.

The WebAssembly preview owns a separate Pyodide kernel. Studio maps semantic
cell references to each runtime's cell IDs and synchronizes JSON-compatible
native `mo.ui` values between the editor and preview. Each cell must construct
the same native controls in the same order in both runtimes. Anywidget comm
state remains with the runtime that created the model.

Run mode serves the configured default at `/` and each named view at
`/<view>/`. Each browser receives an isolated Marimo run session or Pyodide
worker. Studio support routes remain beneath `/_marimo-studio/` and include
the parent ASGI mount and Marimo `base_url`. Native authentication and unrelated
Marimo routes continue through the host.

Notebook query parameters synchronize through each runtime's kernel queue.
Runtime choice, authentication, file selection, transport, and session
parameters remain with the document that owns them.

## Presentation runtime

Python `RuntimeProvider` implementations project runtime-specific data behind
one record. Browser `PresentationRuntime` implementations use the same runtime
ID, validate that data, and return one document-scoped `RuntimeSession`.

The Server runtime connects to a Marimo session. The WebAssembly runtime runs a
derived notebook in Marimo's Pyodide worker. Both runtimes use the presentation
renderer for output plugins, native controls, React portals, value reads, and
anywidget models.

React portals place cell output in `<marimo-cell>` hosts. `mo-value` hosts read
permitted JSON values through the active runtime. A missing cell or value
produces a structured diagnostic on the affected host while healthy regions
continue to render.

## View source lifecycle

Studio serves every view as a native web directory. Relative stylesheets,
modules, images, fonts, JavaScript imports, and CSS `url(...)` references stay
relative to their authored files.

A source refresh stages the document, runtime configuration, view styles, and
selected view at one presentation revision. A valid scriptless HTML change
replaces `#app-shell` while the runtime root remains mounted. CSS refreshes in
place. An HTML or module change in a scripted view reloads its document so the
browser evaluates the module graph through its regular lifecycle. A failed
refresh keeps the last valid shell.

Source reads and writes use content revisions. Writes use atomic replacement
and reject mutable symlink traversal. An external edit refreshes a clean
editor and produces a conflict beside a dirty editor.

## Static export

`marimo_studio.export` resolves one view, validates its projections and output
paths, derives the WebAssembly notebook, and writes a static site. The bundle
contains the authored view, notebook source, notebook `public/` files, static
cell fragments, runtime configuration, and packaged browser assets.

Export uses relative URLs so the directory can be hosted beneath another base
path. It rejects reserved paths, duplicate destinations, file-directory
collisions, and symlink sources before copying. Files are staged beside the
destination and moved into place after the complete bundle has been written.
Replacing an existing destination requires `--force`.

## Change ownership

| Change                                  | Primary owners and checks                                                 |
| --------------------------------------- | ------------------------------------------------------------------------- |
| Configuration, aliases, or source files | `_workspace` and focused Python tests                                     |
| Routes, sessions, or authentication     | `_server`, `_compat/server`, Python tests, and browser acceptance         |
| Browser record or response shape        | Protocol schema, Python producer, browser consumers, and schema tests     |
| Runtime contract                        | `packages/runtime`, Python provider, presentation adapter, and tests      |
| Cell, value, or document lifecycle      | `packages/presentation`, package tests, and browser acceptance            |
| Workspace mode, view, source, or layout | `packages/studio`, package tests, and browser acceptance                  |
| Marimo frontend integration             | `packages/marimo-frontend`, `make build`, and adapter tests               |
| Static export                           | `export.py`, `_compat/static_export.py`, export tests, and `make package` |

Keep a cross-boundary change aligned across Python response models, protocol
schemas, runtime IDs, browser consumers, diagnostics, storage keys, query
parameters, and tests. [Frontend workspace](frontend.md) gives the browser
development loop and package-specific validation commands.
