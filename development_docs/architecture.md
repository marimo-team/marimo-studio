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

| Owner                     | Responsibility                                             |
| ------------------------- | ---------------------------------------------------------- |
| `_workspace`              | Notebook configuration, manifests, and transactions        |
| `_views`                  | View creation, source capabilities, inspection, and builds |
| `view_providers`          | Public provider records, runner ports, and document rules  |
| `view_providers._host`    | Entry-point discovery, conformance, and isolated calls     |
| `view_providers._bundled` | Starter files, source analysis, and candidate builds       |
| `_artifacts`              | Snapshots, immutable revisions, leases, and profile state  |
| `_validation`             | Static, runtime, and browser evidence plus repair actions  |
| `_delivery`               | Live and static runtime composition                        |
| `_notebook`               | Saved notebook inspection and cell identity                |
| `_projections`            | Notebook symbols, target resolution, values, and evidence  |
| `_filesystem`             | Secure path operations and bounded tree traversal          |
| `_processes`              | Supervision, cancellation, and output bounds               |
| `agent`                   | Notebook-bound authoring API and server transport          |
| `_server`                 | HTTP policy, notebook scope, and development coordination  |
| `_compat`                 | Private Marimo imports and reversible host integration     |
| `packages/protocol`       | Serializable browser records                               |
| `packages/runtime`        | Environment-neutral runtime logic                          |
| `packages/presentation`   | One published document and its mount lifecycle             |
| `packages/studio`         | Workspace, Source sessions, view selection, preview frames |
| `apps/browser`            | Browser composition                                        |
| `apps/e2e`                | Live acceptance                                            |

The contributor guide and detailed architecture pages link to this table as
the canonical ownership map.

## Durable records

`view.toml` contains a schema, provider key, and explicit option overrides. The
selected provider applies its defaults while inspecting and building the
project. Starter identity is not durable state.

The public provider protocol contains compact provider info, starters,
creation, inspection, and build. Provider methods are synchronous. Studio runs
them outside the server event loop. External commands use process supervision
and cooperative cancellation.

Artifacts are generated beneath each view's `.artifacts/`. A candidate is
published only after complete validation. The current publication stays
available when a later build fails.

## Dependency direction

- Product policy depends on Studio records and ports.
- Marimo internals stay in `_compat`.
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
- [View providers and artifacts](architecture/view-providers-and-artifacts.md)
- [Symbolic projections](architecture/symbolic-projections.md)
- [Marimo integration](architecture/marimo-integration.md)
- [Browser runtime and authoring](architecture/browser-runtime-and-authoring.md)
- [Agents and delivery](architecture/agents-and-delivery.md)
