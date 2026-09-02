# Contributor guide

Marimo Studio lets one Marimo notebook back several custom web views.
The authoring workspace keeps the notebook, provider-discovered source, build
state, and live preview together. Start a change with the behavior users rely
on, update its semantic owner, and test that behavior through the working
product.

## Understand the product boundary

Marimo owns notebook execution, the reactive graph, sessions, authentication,
WebSockets, virtual files, native routes, output renderers, controls, and
widgets. Studio owns named view projects, provider discovery, artifact
publication, notebook projections, the authoring workspace, runtime selection,
agent evidence, and static packaging.

Read [Architecture](architecture.md) before a change crosses an ownership
boundary. The detailed maps connect each subsystem to the feature that pays
for its complexity.

Use the [canonical ownership map](architecture.md#ownership) to select the
package that owns a policy or mutable resource.

| Change area                                                                 | Architecture map                                                               |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Workspace configuration, `view.toml`, or project transactions               | [Product and workspace](architecture/product-and-workspace.md)                 |
| Revisions, generations, sessions, readiness, or mutation admission          | [Identities and state](architecture/identities-and-state.md)                   |
| View creation, source documents, inspection, builds, removal, or revisions  | [Product and workspace](architecture/product-and-workspace.md)                 |
| Provider descriptors, starters, inspection, builds, or artifact storage     | [View providers and artifacts](architecture/view-providers-and-artifacts.md)   |
| Target Python selection, provider dependencies, or CLI environment re-entry | [Provider environments](architecture/provider-environments.md)                 |
| Notebook symbols, mount declarations, mounted instances, or ownership       | [Symbolic projections](architecture/symbolic-projections.md)                   |
| Marimo routes, sessions, saves, kernels, private APIs, or upgrades          | [Marimo integration](architecture/marimo-integration.md)                       |
| Server routing, authentication, capabilities, or browser isolation          | [Server routing and security](architecture/server-routing-and-security.md)     |
| Browser protocol, runtimes, Source, layout, or presentation lifecycle       | [Browser runtime and authoring](architecture/browser-runtime-and-authoring.md) |
| Error codes, HTTP translation, CLI diagnostics, or validation issues        | [Errors and diagnostics](architecture/errors-and-diagnostics.md)               |
| Agents, CLI validation, export, E2E, or packaging                           | [Agents and delivery](architecture/agents-and-delivery.md)                     |

Use [Frontend workspace](frontend.md) for package commands and browser source
workflow. Use [Documentation delivery](documentation.md) for VitePress, public
examples, and rendered validation. Use [Releasing](releasing.md) for
versioning, publication, and recovery.

## External foundations

These upstream systems define contracts that Studio integrates:

| Foundation                                                                                                                                                            | Role in Studio                                                                               |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| [Marimo](https://docs.marimo.io/)                                                                                                                                     | Reactive notebook execution, sessions, native rendering, authentication, and the editor host |
| [Marimo code mode](https://docs.marimo.io/guides/editor_features/tools/#code-mode)                                                                                    | Coding-agent execution inside the live notebook kernel                                       |
| [Agent Skills](https://agentskills.io/) and [Agent Plugins](https://github.com/peter-gy/agent-plugins)                                                                | Portable agent instructions and their packaged resources                                     |
| [uv](https://docs.astral.sh/uv/) and [PEP 723](https://peps.python.org/pep-0723/)                                                                                     | Python environment selection and dependencies stored in a script                             |
| [Deno](https://docs.deno.com/)                                                                                                                                        | Pinned JavaScript and TypeScript toolchain for bundled framework providers                   |
| [ASGI](https://asgi.readthedocs.io/en/latest/)                                                                                                                        | Interface between Studio's asynchronous Python application and a server                      |
| [WebAssembly](https://webassembly.org/) and [Pyodide](https://pyodide.org/)                                                                                           | Browser-side notebook execution                                                              |
| [Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc) and [Flechette](https://github.com/uwdata/flechette) | Columnar dataframe transfer from Python to browser code                                      |
| [VitePress](https://vitepress.dev/)                                                                                                                                   | Public documentation site generator                                                          |

The architecture pages name the exact adapter, owner, and lifecycle boundary
for each integration.

## Install the workspace

Install the locked Python and JavaScript environments:

```console
make setup
```

`make setup` installs the Python and [pnpm](https://pnpm.io/) JavaScript
workspaces, prepares the pinned Marimo
frontend source, builds Studio's browser assets, and installs Chromium for
browser acceptance tests. Python tooling runs through `uv`. Browser and
documentation tooling runs through the pnpm workspace, where
[Vite Plus](https://viteplus.dev/guide) owns formatting, linting, TypeScript
checks, tests, builds, and task execution.

Deno-backed providers use the exact executable supplied by the Python package
extra. Their frontend dependency versions and lockfiles belong to the view
project or packaged starter that consumes them.

## Work in one owning slice

Use the smallest loop that proves the changed contract:

| Owner                                            | Focused loop                                                |
| ------------------------------------------------ | ----------------------------------------------------------- |
| Python workspace, provider, artifact, or service | `uv run pytest packages/marimo-studio/tests/<test-file>.py` |
| Complete Python profile for the current platform | `make python-test`                                          |
| Frontend workspace                               | `make frontend-test`                                        |
| Protocol                                         | `pnpm --filter @marimo-studio/protocol test`                |
| Runtime SPI                                      | `pnpm --filter @marimo-studio/runtime test`                 |
| Presentation document                            | `pnpm --filter @marimo-studio/presentation test`            |
| Studio workspace                                 | `pnpm --filter @marimo-studio/studio test`                  |
| Marimo frontend facade                           | `pnpm --filter @marimo-studio/marimo-frontend test`         |
| Documentation                                    | `make docs-build`                                           |

Keep tests with the owner of the contract. Add a browser acceptance case under
`apps/e2e` when the result crosses a provider build, native editor, kernel,
filesystem, session, worker, artifact document, or preview.

## Change a boundary deliberately

1. State the user-visible result and the identity or state that must survive.
2. Find the semantic owner in the architecture maps.
3. Add local behavior to that owner.
4. Cross packages with a protocol record, runtime interface, feature port, or
   closeable handle.
5. Cross framework syntax through `ViewProvider.inspect()` and
   `ViewProvider.build()`.
6. Cross private Marimo behavior through the owning feature port,
   `_composition.py`, and one `_compat` or `packages/marimo-frontend` adapter.
7. Update producer, consumer, diagnostic, and contract tests together when a
   boundary shape changes.
8. Add live acceptance when the promise depends on lifecycle ordering or
   several files, documents, processes, or runtime instances.

Studio source follows these dependency directions:

```text
Python policy -> Studio ports -> _compat adapters -> Marimo
              -> ViewProvider -> view_providers._bundled
              -> artifact store

apps/browser -> presentation -> runtime -> protocol
             -> studio -----------------> protocol
presentation -> marimo-frontend --------> Marimo frontend

Studio app -> features -> shared
```

## Trace view work

A view change crosses these contracts:

```text
view.toml
  -> ViewProject
  -> ViewProvider.inspect()
  -> ProjectInspection
  -> immutable input snapshot
  -> project revision
  -> ViewProvider.build()
  -> staging candidate
  -> Studio artifact validation
  -> immutable ViewArtifact
  -> ArtifactLease
  -> PresentationSnapshot
```

Provider inspection returns editor documents, one input scope, mount
declarations, diagnostics, and a build fingerprint. Core enumerates the input
scope for revisions, snapshots, and watching. A document can be visible in
Source while remaining read-only. A binary asset can affect a build while
staying outside the text editor.

## Trace symbolic projection work

Projection changes cross a second path:

```text
provider source
  -> MountDeclaration
  -> artifact instrumentation
  -> mounted ProjectionRequest
  -> NotebookSymbolGraph resolution
  -> runtime cell binding
  -> mounted result
```

Keep source declarations separate from mounted instances. One JSX `map` or
Svelte `each` declaration can mount several hosts, change targets, and release them
independently.

## Finish at the consumer boundary

Run the repository gate:

```console
make check
```

Add the matching boundary checks:

| Change                                                                            | Additional check                                             |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Browser package, protocol, runtime, or Marimo frontend adapter                    | `make build`                                                 |
| Provider entry point, starter resource, or Deno build                             | Provider contract tests and `make package`                   |
| Session, frame, source, projection, control, query, view, or responsive lifecycle | `make e2e`                                                   |
| Generated browser assets or distribution contents                                 | `make package`                                               |
| Public documentation                                                              | `make docs-build` and rendered desktop and narrow inspection |

`make test` runs the complete Python profile for the current platform and the
frontend package tests. `make check` adds formatting, linting, architecture,
provider-source, and type checks. `make docs-build` owns public example exports
and VitePress verification. Live browser acceptance remains the evidence for
cross-document behavior.

`make typecheck` runs ty, Pyrefly, basedpyright, and the TypeScript checks.
Basedpyright analyzes the distributed package against Python 3.10 and analyzes
tests and contributor scripts against Python 3.11. Error diagnostics fail the
type-check gate.

## Keep authored and generated files distinct

Edit repository source under `packages/`, `apps/`, `docs/`,
`development_docs/`, `examples/`, and `skills/`.

`make build` validates the prepared Marimo frontend and writes packaged browser
assets to:

```text
packages/marimo-studio/src/marimo_studio/_static/browser/
```

The prepared Marimo checkout lives under
`packages/marimo-frontend/.cache/`. Both paths are generated and remain
untracked.

`make lint`, `make typecheck`, `make frontend-test`, and `make build` validate
the prepared checkout without changing it. Run `make setup` when readiness
validation reports stale metadata, missing dependencies, or a mismatched
checkout.

A user view owns its build and publication surface beneath the project:

```text
__marimo__/studio/<notebook>/<view>/.artifacts/
```

Studio writes staging candidates, immutable revisions, provider caches, and
profile receipts there. The repository ignores the complete `.artifacts/`
workspace. Source-controlled examples keep the manifest, authored files,
provider configuration, and dependency locks.

Browser acceptance fixtures begin with `view.toml` and provider source. The E2E
fixture setup builds their artifacts in an isolated workspace so the browser
suite proves a cold publication path.

## Keep documentation paired with behavior

Update the surface that owns the reader's question:

| Reader                                      | Source                                                                             |
| ------------------------------------------- | ---------------------------------------------------------------------------------- |
| Product user completing a task              | `docs/guide/`                                                                      |
| User looking up an exact contract           | `docs/reference/`                                                                  |
| Contributor changing ownership or lifecycle | `development_docs/architecture/`                                                   |
| Contributor running a package workflow      | `development_docs/README.md`, `frontend.md`, `documentation.md`, or `releasing.md` |
| Coding agent following the authoring loop   | `skills/marimo-studio/` and the public agent guide                                 |

Public docs explain the capability and user consequence. Development docs
explain owners, invariants, lifecycle, and validation.
