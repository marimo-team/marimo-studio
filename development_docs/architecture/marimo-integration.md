# Marimo integration

Marimo remains the notebook process, reactive runtime, editor, session system,
and output renderer. Studio depends on those capabilities through owned ports
and pinned adapters. Product policy imports ports. Private `marimo._*` imports
stay inside `_compat`.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Boundary map

```text
Studio product policy
  -> feature-owned ports
  -> _composition.py
  -> _compat adapters
  -> pinned Marimo release

Presentation browser code
  -> packages/marimo-frontend named facade
  -> prepared pinned Marimo frontend source
```

This boundary lets an upstream change replace one adapter while workspace,
provider, artifact, projection, browser, and agent policy stay stable.

## Product capabilities backed by Marimo

| Studio capability           | Marimo behavior                                          | Studio owner                                       |
| --------------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| Static notebook graph       | Compile cells, names, definitions, references, and edges | `StaticNotebookLoader` adapter                     |
| Native cell projections     | Existing cell results and control lifecycle              | Runtime cell adapter                               |
| Rich output projections     | Formatter output, widgets, files, and cleanup            | `KernelProjectionHost` and projected-output facade |
| Live values                 | Kernel value reads and browser serialization             | Kernel values adapter                              |
| Server preview              | Existing application and session                         | Server gateway and session adapters                |
| WebAssembly preview         | Browser notebook source and worker runtime               | `BrowserRuntimeProjector` and frontend facade      |
| Prepared static view        | Cache-backed values and rendered snapshots               | marimo-export and `_prepared`                      |
| Notebook editing            | Native editor document                                   | Studio workspace frame                             |
| Save-time alias maintenance | Notebook persistence boundary                            | `NotebookSaveTransform`                            |
| Query and controls          | Session transport and peer state                         | Query and control adapters                         |
| Static export               | Browser runtime or prepared publication                  | `_delivery` and `_prepared`                        |

## Python ports

Feature packages define records and ports that use Studio nouns:

- `_notebook/ports.py` owns static inspection, runtime probes, and environment flags.
- `_server/ports.py` owns Marimo server and session adapters.
- `_server/presentation/ports.py` owns kernel projection behavior.
- `_delivery/ports.py` and `_delivery/browser_ports.py` own export and browser projection.
- `_browser_client/ports.py` owns the code-mode bridge. `_composition.py` constructs
  separate notebook loader, runtime probe, environment flag, and code-mode
  adapters.

Composition keeps tooling adapters independent and groups coupled server and
export lifecycles into process-facing bundles.

### Tooling factories

- `create_static_notebook_loader()`
- `create_runtime_probe()`
- `create_environment_flag_builder()`
- `create_code_mode_bridge()`

Each caller constructs the one adapter it consumes.

### Server composition

The server bundle groups Marimo gateway, session, persistence, projection,
peer, browser-runtime, code-mode, and lifecycle adapters. The ASGI middleware
receives one bundle per application composition. Feature modules depend on
their narrow ports, while `_composition.py` owns the concrete bundle shape.

`StudioRoutePolicy` is immutable composition input beside the adapter bundle.
Route handlers read no process environment.

### `ExportAdapters`

- `BrowserRuntimeProjector`
- `StaticRuntimeConfigLoader`

WebAssembly export uses this bundle to add a browser notebook runtime to a
production view artifact. Prepared export compiles the provider's immutable
mount declarations into a marimo-export specification, resolves finite input
states through the cache-backed producer, and publishes its verified result
index beside the artifact. Static exports open marimo-export's configured
persistent repository. Exact producer, output-plan, and state-space identities
therefore reuse one prepared generation across commands and documentation
builds.

Static delivery uses `marimo_export.delivery.stage()` as the outer transaction.
Studio writes its provider artifact, runtime configuration, manifest, and
public files into the staged application directory. `StagedDelivery.materialize()`
writes the prepared export under its immutable instance path. Studio's guard
revalidates notebook, catalog, view generation, and prepared publication state
immediately before `StagedDelivery.commit()` verifies and installs the complete
directory.

`states.yaml` uses the public `marimo_export.StateSpace` schema. Studio reads
the file through its secure filesystem boundary, then marimo-export validates
and expands the state space. Studio infers `OutputSpec` values from the view's
projection mounts and combines both parts into one `ExportSpec`.

The managed producer gives Marimo the authored notebook path as its logical
runtime filename. Marimo therefore reads and writes the notebook's shared
`__marimo__/cache/` directory even though execution uses a guarded source copy
and Studio stages portable outputs through the export repository. The export
repository retains verified materializations. Marimo's native cache owns
computation reuse. A second view can request another output plan over the same
states and restore matching authored cells from those native entries. Its
distinct projection leaves produce new receipts once, then remain reusable as
prepared states. `StaticExportResult.cache_activity` exposes the native authored
and projection dispositions reported by marimo-export.

### Prepared preview publication

`PreparedViewRegistry` adapts a view to marimo-export's
`PreparedPublicationController`. `_prepared/resolve.py` compiles the view's
outputs, plans them, and calls `Session.observe_inputs(plan=plan)` for the
complete current input record. Marimo-export owns input normalization and
producer validation, including ordinary Python inputs and UI controls.

Studio decides which states belong to the view. With `states.yaml`, it keeps
the configured finite state space and selects the current inputs when they
match a planned state. With no state file, it uses the current input record as
`baseline` and adds recorded observations. Marimo-export executes each state
in a child notebook graph inside the borrowed editor kernel. The child owns
its controls, outputs, and cleanup while the editor retains its live state.

The registry keys current publications by view, editor binding, and
presentation revision. The state-space source digest belongs to candidate
metadata. Its admission callback revalidates the source before export commits
the candidate. A failed replacement retains the current publication, including
when `states.yaml` is invalid. Current-manifest reads consume that admitted
publication.

Studio supplies the observation-revision predicate to
`PreparedPublicationController.poll()`. The export controller runs the
predicate off the event loop and owns refresh work, cancellation, candidate
cleanup, and retained generations. Studio releases publications when their
editor binding or notebook scope closes.

Keep ports shaped around Studio operations. A port should return stable
records and lifecycle handles, not private Marimo objects.

## Composition roots

`_composition.py` validates the pinned release before constructing adapters:

- separate tooling factories for notebook loading, runtime probing,
  environment flags, and code mode
- `create_server_adapters()` for ASGI presentation and live sessions
- `create_export_adapters()` for static export
- `create_browser_runtime_projector()` for WebAssembly runtime material
- `kernel_lifespan()` for kernel-side projection support
- `programmatic_middleware()` for programmatic notebook serving

Feature modules import these factories or the ports they return. They do not
construct `_compat` implementations directly.

## Pinned release identity

`_compat/release.json` records:

- Supported Marimo version
- Upstream tag commit
- Private Python layout fingerprints
- Browser frontend source identity

`validate_marimo_release()` checks the installed distribution before a private
adapter runs. Browser asset metadata records the same version and commit.

The Python pin, release manifest, prepared frontend checkout, generated browser
assets, and adapter tests form one compatibility unit.

## Static notebook inspection

The private notebook adapter compiles the saved notebook and returns
`StaticNotebook`:

```python
StaticNotebook(
    cells=(
        StaticCell(
            runtime_id="...",
            code="...",
            name="filters",
            definitions=("selected_artist",),
            references=("df",),
            parents=(...),
            children=(...),
            source=SourceSpan(...),
        ),
    ),
    app_config={...},
)
```

Studio converts this to `NotebookSpec` and then `NotebookSymbolGraph`. Static
inspection compiles notebook structure and avoids running cell bodies.

Native cell names enter the cell target namespace. Configured aliases are
resolved against semantic `CellRef` values and join the same namespace.
Variable definitions and references become producer, consumer, upstream, and
downstream graph edges.

## Semantic and runtime cell identity

`CellRef` identifies a notebook cell from stable semantic source information.
Marimo runtime IDs identify one compiled or live runtime instance.

```text
provider target
  -> NotebookSymbolGraph
  -> semantic CellRef
  -> runtime-specific cell ID
```

`ResolvedStudio.runtime_cell_refs()` maps semantic refs to runtime IDs. For a
Server runtime it matches the current live session snapshot. For WebAssembly it
uses the inspected notebook runtime IDs embedded in the projection.

Keep semantic resolution ahead of runtime mapping. Browser requests and saved
view source should never depend on a transient runtime ID.

## Server gateway and routing

`ServerGateway` translates Marimo ASGI state into `ServerLocation` and
`ServerContext` records:

- Canonical notebook path and file-routing key
- Base URL and route query
- Edit or run mode
- User and override configuration
- Process-bound server token
- Opaque server handle

`PresentationMiddleware` consumes those records and delegates native Marimo
paths before dispatching Studio work. Read [Server routing and
security](server-routing-and-security.md) for route recognition, workspace
lifecycle, authentication, presentation capabilities, iframe isolation, and
native-session admission.

## Notebook-scoped services

`NotebookScopeRegistry` creates one `NotebookScope` per canonical notebook:

```text
NotebookScope
  -> NotebookPresentation
  -> StudioClientRegistry
  -> AgentCoordinator
  -> build and artifact activity for that notebook
```

ASGI lifespan closure releases agent requests, browser clients, provider
workers, artifact pins, and notebook-scoped handles. Each close operation is
idempotent and preserves the first failure while attempting remaining cleanup.

## Server session integration

The Server runtime projects into an existing Marimo session.

`SessionState` answers whether a session exists and returns a live cell
snapshot. `ExistingSessionAttachment` attaches a preview or agent consumer to
that exact session. `SessionReplay` records documents whose reconnects should
resume the session.

The runtime configuration includes a process-bound server instance and a
runtime instance digest. Browser requests also carry the current session ID.
The server rejects requests whose revision, runtime, or session identity does
not match the selected presentation.

### Sandboxed kernels

`marimo edit --sandbox` and `marimo run --sandbox` start each kernel or app
host in an environment built from the notebook's PEP 723 manifest. Studio's
kernel half loads through the `marimo.kernel.lifespan` entry point, so that
environment must contain the Studio the server runs. `SandboxRuntime` layers
it through Marimo's `RuntimeOverlay`, the same mechanism that binds the kernel
to the running Marimo. It appends one requirement for the lifespan of the
server adapters: `-e <path>` for an editable checkout, the file URL of a local
wheel or directory, or `marimo-studio==<version>` for an index install. When
the server has Deno, the overlay also pins `deno==<version>`, because code mode
authors and builds framework views inside the kernel. An overlay entry takes
precedence over the manifest's own requirement, and the manifest is never
edited.

## Kernel projection host

`KernelProjectionHost` supplies three operations:

- Read value selector specifications
- Render output selector specifications with active-owner state
- Synchronize query parameters into the session

Studio resolves projection requests before calling this port. The adapter
receives selector specifications derived from the notebook graph and source
site. For each request, the server signs the producer and every semantic
`CellRef` and live cell ID in its dependency closure. The kernel validates that
complete binding immediately before it reads a value or renders an output. It
recomputes the current live closure and requires the same ordered `CellRef` and
runtime ID pairs. An edit inside the closure, including a newly resolved
upstream producer, makes a retained presentation stale. An edit in an
independent branch leaves the capability valid.

The adapter owns Marimo kernel calls, output formatting, virtual files,
widgets, and resource cleanup.

Projected output ownership is explicit. A selector stays active while its
final presentation owner remains mounted. Value reads can share one kernel
request across several hosts.

### Development preview overlays

`KernelOutputRenderer` accepts an optional `overlays` callback that selects
named display objects from the notebook namespace. The callback manages objects
it creates; the renderer owns their formatted native resources. The existing output
response carries these overlays alongside requested projections. Stable
objects retain their native output resources; completed notebook runs refresh
the selection through the existing output reader.

In edit mode, the private Lens adapter reuses an open notebook Lens, including
anonymous outputs created by Marimo's auto-mount hook. Otherwise, when Lens is
installed, it owns one instance with `STUDIO_RESULT_SELECTOR`. Borrowed
instances keep their configured selector and notebook ownership.

Lens gives each document its own interaction owner, so the notebook dock and
the preview dock drive one Lens model. Lens 0.2.1 and newer bounds its notebook
UI to Marimo's `#App` pane, which Studio places inside the Notebook pane.

Marimo mounts its Lens after the cell that imports marimo runs, unless an
earlier cell output already holds one. That cell usually runs before a cell that
constructs a Lens, so a notebook that authors its own Lens would hold two. The
kernel lifespan replaces the post-execution hook with `LensMountPolicy`, which
skips the automatic mount when a Studio notebook imports the `Lens` widget or
the `marimo_lens` module.
Other notebooks keep Marimo's mount.

The native renderer mounts overlays outside the artifact shell, suppressing
widgets already projected in the view. Widget model IDs and native virtual
files retain their authenticated kernel scope across development view
replacements. Other native requests keep their revision checks. Run mode,
WebAssembly, and static delivery do not create overlays.

## WebAssembly runtime projection

`BrowserRuntimeProjector` builds `BrowserRuntimeProjection` from the saved
notebook source. The record includes:

- Runtime instance identity
- Pinned Marimo version and commit
- Browser notebook code
- Compiled execution cells
- Projection bootstrap cell ID

The browser worker loads the saved notebook into Marimo with automatic cell
execution disabled. Python precomputes each available target, producer, and
dependency closure from the notebook graph and artifact mount declarations.
The runtime checks mounted requests against those records, schedules required
cells through Marimo's cell queue, and attaches each host to its worker cell.
Dynamic retargeting schedules newly required cells while the worker and its
executed state remain mounted.

The dependency closure drives execution and remains symbolic evidence for
inspection and validation. An independent branch with incompatible code does
not block a view that never mounts that branch.

Browser runtime assets come from `packages/marimo-frontend` and the browser
build. The projector checks that their release metadata matches the Python
adapter release.

## Frontend facade

`packages/marimo-frontend` exposes named capabilities around upstream source:

- Embedded runtime
- Cell presentation
- Projected output
- Prepared presentation
- Session bootstrap
- Control endpoint
- Theme frame
- Vite preparation

Presentation imports these names. Upstream atoms, stores, providers,
registries, transports, aliases, and source paths remain inside the facade.

Stateful facade capabilities return explicit dispose or close handles. The
presentation projection owner decides when to release them.

## Notebook persistence

`NotebookSaveTransform` installs a source policy at Marimo's durable save
boundary. The policy can update configured aliases when semantic cell refs
change and commits its metadata update after the notebook write succeeds.

Native named cells need no configured binding. Example notebooks and primary
authoring workflows should use native names. Alias APIs remain available for
anonymous cells and explicit product naming.

Keep save transformation scoped to the attached notebook session. Session
detach or adapter shutdown closes its policy handle.

The editor bridge treats a successful first save as a session handoff from the
temporary `__new__*` file key to the saved notebook. It requests Studio reload
through that exact native session after the saved path exists. Read [Product
and workspace](product-and-workspace.md#first-save) for the complete lifecycle.

Notebook document transactions pause active presentations before durable
mutation, then settle after the matching save and presentation build. The
Preview owner coordinates that barrier. Marimo remains the durable notebook
writer. Read [Product and workspace](product-and-workspace.md#notebook-mutation-admission)
for the mutation state machine.

## Controls, query, and peer state

Controls are Marimo runtime resources projected into a view. Their state stays
with the runtime instance that owns them. Runtime switching reconnects hosts to
the selected instance.

Query synchronization uses explicit operation IDs so editor, preview, and
history updates can identify their own echoes. Peer command adapters relay
authorized control state between consumers of one session.

## Private adapter lifecycle

`_PrivateAdapterLifecycle` opens server integrations as one ordered group. A
partial startup closes handles already opened. ASGI shutdown closes notebook
scopes before the application-owned adapter group. The process-wide
presentation-authorization patch is installed by the Marimo entry point and
closes through `atexit` when the Python process exits.

Use explicit lifecycle verbs:

- Install a process patch.
- Attach a consumer to a session.
- Mount a runtime.
- Register a replay document.
- Detach a consumer.
- Close a patch or session adapter.
- Dispose a browser resource.

Avoid global mutation outside an installed handle.

## Upgrade the pinned release

A Marimo upgrade changes one compatibility unit:

1. Update the exact Python requirement and lockfile.
2. Update `_compat/release.json` version, commit, and private fingerprints.
3. Inspect upstream implementations used by every `_compat` adapter.
4. Update private adapter tests and behavior probes.
5. Prepare the exact frontend source.
6. Rebuild browser assets and verify build metadata.
7. Run Python, frontend, Server, WebAssembly, export, and package gates.
8. Exercise bundled Vanilla, React, and Svelte views in a live browser.

Use a clean local Marimo checkout at the configured commit with:

```console
export MARIMO_REPO=/path/to/marimo
make setup
```

Keep `MARIMO_REPO` set while running frontend gates. The prepared source
metadata must match the release manifest.

## Test the boundary

Add tests at the narrowest owner and at the live seam:

| Contract                      | Focused evidence                | Live evidence                                          |
| ----------------------------- | ------------------------------- | ------------------------------------------------------ |
| Static notebook graph         | Adapter and symbol graph tests  | Named targets resolve in the provider runtime fixture  |
| Semantic-to-runtime mapping   | Cell-ref matching tests         | Session reconnect and WebAssembly mount                |
| Kernel values and outputs     | Port and adapter tests          | Native controls, tables, plots, widgets, and downloads |
| Session attachment and replay | Lifecycle tests                 | Run-mode reconnect and preview reload                  |
| Save transform                | Source policy tests             | Notebook edit and durable save                         |
| Browser projector             | Execution catalog tests         | WebAssembly closure selection and dynamic retargeting  |
| Prepared publication          | State and admission tests       | State changes retain editor and prior preview          |
| Frontend facade               | Package tests                   | Browser build and runtime acceptance                   |
| Release identity              | Fingerprint and metadata checks | Isolated wheel installation                            |

Run `make build` and `make e2e` after changing Marimo integration. Run
`make package` when the release manifest, browser assets, entry points, or
distribution contents change.

## Lens client metadata

Studio translates resolved projections into Lens's declarative DOM contract.
`data-marimo-lens-cell-id` identifies the runtime producer, and
`data-marimo-lens-selector` retains the symbolic value selector. Runtime cell
updates publish both native rendering metadata and the Lens source in one path.
Reset releases these source attributes with the projection host.

Descriptions use `data-marimo-lens-label`, `data-marimo-lens-detail`, and
`data-marimo-lens-render-source`. The default rendering reference comes from the
projection's authored source location. Authored descriptions take precedence and
remain owned by the author through projection updates and teardown.

Custom rendered regions use `data-marimo-lens-inputs` to reference existing
source hosts. `data-marimo-lens-context` marks a preferred image container. Lens
captures descriptions at selection creation and keeps them through History and
reopen. Notebook sources, rendering references, and capture containers have
separate roles: Python supplies analytical provenance, client paths describe
rendering code, and context containers guide images.
