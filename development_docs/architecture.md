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

| Owner                                                                 | Responsibility                                                                     |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Marimo                                                                | ASGI lifecycle, auth, sessions, kernels, native APIs, and virtual files            |
| `_entrypoints`                                                        | Register Studio middleware and the kernel lifespan extension                       |
| `_composition.py`, `_capabilities.py`                                 | Construct Marimo adapters and define the stable ports consumed by Studio policy    |
| `_workspace`                                                          | Resolve definitions, workspaces, targets, aliases, views, checks, and source files |
| `app.py`, `checks.py`, `environment.py`, `inspect.py`, `workspace.py` | Compose workspace rules with Marimo adapters at public boundaries                  |
| `_compat`                                                             | Translate private Marimo APIs into Studio-owned records                            |
| `_server`                                                             | Translate authenticated HTTP requests into Studio services                         |
| `export.py`                                                           | Package one resolved view as a static WebAssembly site                             |
| `_cli`                                                                | Adapt Click commands and output formats to application services                    |

`_workspace` accepts `NotebookInspector` and `RuntimeProber` ports when a
rule needs notebook data. It imports no compatibility adapter. `_cli` and
`_server` also stay independent of concrete `_compat` modules. The composition
module exposes fixed roots for server, kernel, tooling, programmatic app, and
static-export processes. Each root validates the pinned release before it
constructs a private adapter and injects the narrow port into Studio policy.

Private imports beginning with `marimo._` stay in `_compat`. Ruff enforces the
boundary. Compatibility code converts Marimo sessions, graph state, requests,
and kernel messages into records owned by `marimo_studio.types` or
`_workspace`.

### Marimo release

Studio supports the tagged Marimo `0.23.16` release. Python dependencies use
an exact version pin. The frontend source uses the commit behind that tag, and
the browser build records the same version and commit in `build-meta.json`.

`_compat/release.json` is the shared version and commit source for the Python
and frontend adapters. `_compat/layout.py` contains the private symbols whose
behavior Studio depends on. Adapter construction checks the installed version,
signatures, and source fingerprints before Marimo starts serving Studio routes.
Packaged browser assets must report the configured version and commit.

To update Marimo:

1. Change the version and tag commit in `_compat/release.json`.
2. Change the exact dependency pins in both Python project files and refresh
   `uv.lock`.
3. Update the support labels in `README.md`, this guide, and
   `docs/reference/python-api.md`.
4. Capture the new signatures and fingerprints:

   ```console
   uv run --frozen python -m marimo_studio._compat.layout > /tmp/marimo-symbols.json
   ```

5. Update the affected contracts in `_compat/layout.py`, then run the
   compatibility tests.
6. Rebuild the browser assets and run the full browser acceptance suite.

`marimo-studio check --format json` includes a `compatibility` record with the
Studio version, required release, observed Marimo and browser identities,
adapter family, and validation state. Observed identities are `null` when
release validation fails.

### Notebook-scoped services

Each canonical notebook path has one `NotebookScope`. The scope composes three
peer services with distinct state:

```text
NotebookScope
  |-> NotebookPresentation
  |     `-> source discovery, immutable snapshots, and revision history
  |-> StudioClientRegistry
  |     `-> connected browsers, Marimo sessions, active views, and query claims
  `-> AgentCoordinator
        `-> acknowledged activations and ordered browser observations
```

`NotebookPresentation` reads authored source and caches immutable presentation
snapshots. `StudioClientRegistry` owns browser presence and session binding.
Runtime configuration and query synchronization consume that registry
directly. `AgentCoordinator` captures immutable browser targets from the
registry and owns one activation or observation operation for each targeted
browser. Agent state does not sit on the presentation cache.

`NotebookScopeRegistry` creates these services on demand and closes them with
the Marimo server lifespan. Cache hits reuse the existing scope. Shutdown
attempts every scope, client registry, agent coordinator, and server adapter,
then reports the first failure. HTTP adapters receive the specific peer they
need.

### Workspace lifecycle

`resolve_workspace_lifecycle` resolves one request into one tagged state:

| State          | Data carried                                                |
| -------------- | ----------------------------------------------------------- |
| `Unconfigured` | Canonical notebook path                                     |
| `NeedsView`    | Valid definition and first-view initialization error        |
| `Ready`        | Valid definition and materialized workspace                 |
| `Invalid`      | Configuration or source error and any discovered definition |

Middleware authenticates and resolves the notebook before creating this
state. Route handlers then match the state to delegation, initialization,
view serving, or a structured error. The state is request-scoped, so source
changes take effect on the next request and each response uses one coherent
definition and workspace.

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

Studio app composition owns cross-feature workspace events.
`WorkspaceEventCoordinator` owns the event stream, decodes activation,
observation, source, and editor-session events, calls `ViewController` for
view selection, calls `PreviewDeck` for preview work, and sends activation
acknowledgements through its remote. `ViewController` owns view inventory and
mutations. Preview features own runtime frames, observations, controls, and
query synchronization.

## Activation

The Python distribution registers two Marimo entry points:

```toml
[project.entry-points."marimo.server.asgi.middleware"]
marimo-studio = "marimo_studio._entrypoints:server_middleware"

[project.entry-points."marimo.kernel.lifespan"]
marimo-studio = "marimo_studio._entrypoints:kernel_lifespan"
```

The middleware resolves a `StudioDefinition` from PEP 723 metadata or the
nearest matching `pyproject.toml`. A definition contains notebook and runtime
configuration and can exist before authored view files. Once at least one view
exists and `default` selects it, Studio materializes a `StudioWorkspace`.
Configured view files live under `__marimo__/studio/<notebook-stem>/<view>/`.
Requests for another notebook continue through Marimo.

The kernel extension registers guarded projection functions in each
file-backed edit kernel. It initializes value reads and native output
formatting when a Studio definition first appears. A materialized view can use
the cell aliases and value references present in its resolved document.
Requests travel through Marimo's kernel queue.

## Edit and run sessions

Edit mode serves the workspace at `/studio/<view>/`. The workspace keeps the
native editor and one frame per available preview runtime mounted while the
layout, selected view, or visible runtime changes. It prepares the selected
runtime and the WebAssembly preview in the background.

When a definition has zero views, authenticated edit mode serves the first-view
initializer. `POST /_marimo-studio/views` creates the configured default and
transitions the next request to a materialized workspace. Run mode returns a
structured `workspace-not-initialized` repair response until that transition
completes.

Agent view activation follows one desired-state contract. The editor transport
binds each Marimo session ID to the client ID of its containing Studio tab. A
mounted workspace receives a targeted activation event, switches through its
view controller, and acknowledges the completed transition. A native editor
receives Marimo's query update and page reload after code-mode execution
releases its scratchpad lock. The private view hint selects the Studio landing
route and is removed from the redirected URL.

Agent analysis returns through an authenticated Studio server route. The
compatibility layer exposes Marimo's callback credentials and session ID to
code mode. The agent client authenticates the connection handshake, receives a
Studio mutation token, and uses it for the request. Runtime validation runs in
a supervised child process with bounded output, timeout, cancellation, and
owned-process termination. Browser validation sends a fresh request ID, source
revision, runtime, and runtime instance to the bound client. The server accepts
ordered observations that match that request and joins them with the runtime
result from the same source revision.

On POSIX, the owned boundary is the worker's new process group. Notebook code
that starts another process session leaves that boundary and may outlive
validation. On Windows, a kill-on-close Job Object retains the worker and its
descendants.

The Server preview joins the editor's Marimo session as a kiosk consumer after
the editor session exists. It reuses that kernel's outputs, native controls,
and anywidget models. Studio relays authorized native control commands to peer
consumers before kernel application.

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

`mountEmbeddedRuntime(options)` is the Marimo frontend composition seam. Its
handle owns the provider tree, transport configuration, notebook connection,
theme subscription, session exposure, updates, and disposal. Presentation
supplies document policy and projection readers through the facade contract.

`PresentationRevisionController` owns each document transition. It cancels a
superseded generation, marks presentation readiness as loading, stages the
document and runtime configuration, commits or rolls back the authored shell,
hands the revision to the mounted runtime, preserves a run session across a
required page reload, and publishes the terminal readiness state. The
`DocumentRevisionAdapter` owns DOM, stylesheet, history, base URL, and runtime
configuration mutations for that transaction. Standalone navigation and the
development event loop use the same controller instance.

Rendered observation is split from readiness state. `ReadinessController`
reduces runtime, presentation, and projection host states. The rendered-view
observer owns DOM probing, diagnostics, the public `window.marimoStudio` API,
and parent-frame readiness messages. The agent observer owns the current
observation request and emits loading or terminal evidence for its exact view,
revision, runtime instance, and session.

React portals place complete cell output in `<marimo-cell>` hosts and formatted
Python objects in `<marimo-output>` hosts. The output bridge resolves an
allow-listed value reference, formats it through Marimo's native registry, and
owns formatter-created resources under a stable presentation cell ID.
`mo-value` hosts read permitted JSON values through the active runtime. A
missing projection produces a structured diagnostic on the affected host while
healthy regions continue to render.

`ProjectionHostRuntime` composes cell, output, and value adapters. It owns host
registration, connection and disposal, staged-document preparation, live-host
preservation, change notification, and the projection readiness contribution.
Each adapter keeps its selector and rendering semantics. A new projection host
joins the document lifecycle through this adapter list.

## View source lifecycle

Studio serves every view as a native web directory. Relative stylesheets,
modules, images, fonts, JavaScript imports, and CSS `url(...)` references stay
relative to their authored files.

A source refresh runs one revision transaction for the document, runtime
configuration, view styles, and selected view. A valid scriptless HTML change
replaces `#app-shell` while the runtime root remains mounted. CSS refreshes in
place. An HTML or module change in a scripted view reloads its document so the
browser evaluates the module graph through its regular lifecycle. A failed
refresh keeps the last valid shell and publishes its diagnostic.

Source reads and writes use content revisions. Writes use atomic replacement
and reject mutable symlink traversal. An external edit refreshes a clean
editor and produces a conflict beside a dirty editor.

Removing the selected view is an ordered transition. Studio saves its source,
selects and prepares the successor, retargets preview and source streams,
deletes the old directory, then commits the returned inventory.

## Static export

`marimo_studio.export` resolves one view, validates its projections and output
paths, asks the shared `BrowserRuntimeProjector` for the WebAssembly record,
and writes a static site. Server previews use the same projector, so version,
commit, notebook identity, code, and selector specifications have one producer.
The bundle
contains the authored view, notebook source, notebook `public/` files, static
cell fragments, runtime configuration, and packaged browser assets.

Export uses relative URLs so the directory can be hosted beneath another base
path. It rejects reserved paths, duplicate destinations, file-directory
collisions, and symlink sources before copying. Files are staged beside the
destination and moved into place after the complete bundle has been written.
Replacing an existing destination requires `--force`.

## Change ownership

| Change                                     | Primary owners and checks                                                 |
| ------------------------------------------ | ------------------------------------------------------------------------- |
| Configuration, aliases, or source files    | `_workspace` and focused Python tests                                     |
| Routes, sessions, or authentication        | `_server`, `_compat/server`, Python tests, and browser acceptance         |
| Browser record or response shape           | Protocol schema, Python producer, browser consumers, and schema tests     |
| Runtime contract                           | `packages/runtime`, Python provider, presentation adapter, and tests      |
| Cell, output, value, or document lifecycle | `packages/presentation`, package tests, and browser acceptance            |
| Workspace mode, view, source, or layout    | `packages/studio`, package tests, and browser acceptance                  |
| Marimo frontend integration                | `packages/marimo-frontend`, `make build`, and adapter tests               |
| Static export                              | `export.py`, `_compat/static_export.py`, export tests, and `make package` |

Keep a cross-boundary change aligned across Python response models, protocol
schemas, runtime IDs, browser consumers, diagnostics, storage keys, query
parameters, and tests. [Frontend workspace](frontend.md) gives the browser
development loop and package-specific validation commands.
