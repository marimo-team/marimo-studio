# Architecture

Marimo Studio turns one saved Marimo notebook into several custom web views.
Keep each decision with one owner and cross boundaries through compact records.

```text
notebook configuration
  -> view project
  -> provider inspection
  -> immutable input snapshot
  -> candidate build
  -> validated publication
  -> presentation
  -> browser mounts
```

## Ownership

| Owner                      | Responsibility                                             |
| -------------------------- | ---------------------------------------------------------- |
| `_workspace`               | Notebook configuration, manifests, and transactions        |
| `_views`                   | View creation, Source capabilities, inspection, and builds |
| `view_providers`           | Public provider records and document rules                 |
| `view_providers._host`     | Entry-point discovery, conformance, and contained calls    |
| `view_providers._bundled`  | Starter files, source analysis, and candidate builds       |
| `_artifacts`               | Snapshots, immutable revisions, leases, and profile state  |
| `_validation`              | Static, runtime, and browser evidence plus repair issues   |
| `_delivery`                | Live and static runtime composition                        |
| `_notebook`                | Saved notebook inspection and cell identity                |
| `_projections`             | Notebook symbols, target resolution, values, and evidence  |
| `_filesystem`              | Secure path operations and bounded tree traversal          |
| `_processes`               | Supervision, cancellation, and output bounds               |
| `_authoring`               | Shared workspace and view application operations           |
| `_browser_client`          | Browser selection, observation, protocol, and transport    |
| `authoring`                | Saved-notebook public authoring interfaces                 |
| `agent`                    | Current-code-mode public authoring interfaces              |
| `_cli`                     | Command parsing, environment re-entry, diagnostics, output |
| `_server`                  | HTTP policy, notebook scope, sessions, and coordination    |
| `errors`                   | Stable domain error codes and recovery details             |
| `_composition.py`          | Concrete Python adapter construction                       |
| `_entrypoints.py`          | Marimo middleware and kernel plugin entry points           |
| `_compat`                  | Private Marimo Python imports and reversible integration   |
| `_release_checks`          | Browser asset budgets and package metadata checks          |
| `packages/protocol`        | Serializable browser records                               |
| `packages/runtime`         | Runtime registry and mounted-session interface             |
| `packages/presentation`    | One published document and its mount lifecycle             |
| `packages/studio`          | Workspace, Source sessions, view selection, preview frames |
| `packages/marimo-frontend` | Private Marimo frontend imports and named adapters         |
| `apps/browser`             | Browser composition                                        |
| `apps/docs`                | VitePress navigation, examples, build, and verification    |
| `apps/e2e`                 | Live acceptance                                            |

The contributor guide and detailed architecture pages link to this table as
the canonical ownership map.

## Durable records

`view.toml` contains a schema, provider key, and explicit option overrides. The
selected provider applies its defaults while inspecting and building the
project. Starter identity is creation-time input.

The public provider protocol contains compact provider info, starters,
creation, inspection, and build. Provider methods are synchronous. Studio runs
them outside the server event loop. External commands use process supervision
and cooperative cancellation.

Artifacts are generated beneath each view's `.artifacts/`. A candidate is
published after complete validation and a final source-identity check. The
current publication stays available when a later build fails.

Read [Identities and state](architecture/identities-and-state.md) for the
canonical revision, generation, session, and readiness ledger.

## Dependency direction

- Product policy depends on Studio records and ports.
- Private Marimo Python imports stay in `_compat`.
- Private Marimo frontend imports stay in `packages/marimo-frontend`.
- Frontend syntax stays in `view_providers._bundled`.
- Providers do not receive artifact, presentation, session, browser, or agent
  owners.
- Protocol performs no I/O.
- Runtime imports protocol and performs no framework or Marimo I/O.
- Studio follows `app -> features -> shared`.

## Mutable owners

| State                   | Owner                    | Release boundary                 |
| ----------------------- | ------------------------ | -------------------------------- |
| Notebook services       | Notebook scope registry  | Application lifespan             |
| Source document session | Source controller        | Document disposal                |
| Development generation  | Development coordinator  | Last subscriber or view deletion |
| Build candidate         | Artifact publisher       | Publication or failure           |
| Published revision      | Artifact store           | Final pin                        |
| Presentation            | Presentation transaction | Replacement or disconnect        |
| Browser mount           | Projection host runtime  | Host removal or target change    |
| Agent request           | Agent coordinator        | Completion or cancellation       |

## Validation boundary

Local records prove policy. Browser acceptance proves composition. A
cross-boundary change should trace:

```text
user behavior
  -> state owner
  -> Studio record or port
  -> adapter
  -> lifecycle boundary
  -> contract test
  -> live browser case
```

Run focused tests while editing and `make check` before handoff. Run
`make build` and `make e2e` after changes that cross Python, browser, artifact,
runtime, document, or session boundaries.

- [Product and workspace](architecture/product-and-workspace.md)
- [Identities and state](architecture/identities-and-state.md)
- [View providers and artifacts](architecture/view-providers-and-artifacts.md)
- [Provider environments](architecture/provider-environments.md)
- [Symbolic projections](architecture/symbolic-projections.md)
- [Marimo integration](architecture/marimo-integration.md)
- [Server routing and security](architecture/server-routing-and-security.md)
- [Browser runtime and authoring](architecture/browser-runtime-and-authoring.md)
- [Errors and diagnostics](architecture/errors-and-diagnostics.md)
- [Agents and delivery](architecture/agents-and-delivery.md)
