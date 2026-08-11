# AGENTS.md

Marimo Studio turns one reactive Marimo notebook into several authored web
views. The notebook remains the executable source for data, transformations,
controls, and domain decisions. Each view gives an audience its own structure,
language, interaction, and route through ordinary HTML, CSS, JavaScript, and
native Marimo results.

## Reason from the product boundary

Start every change with the user behavior it must preserve.

| Product decision                                         | User benefit                                                                          | Architectural owner                                    |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| One notebook backs several named views                   | A dashboard, operations page, and executive brief share one analytical model          | Workspace configuration and view files                 |
| Notebook results remain native                           | Tables, plots, controls, downloads, and anywidgets retain Marimo behavior             | Marimo runtime plus presentation projection hosts      |
| Views are complete web documents                         | Authors can use responsive CSS, modules, assets, browser APIs, and components         | Presentation document runtime                          |
| Authoring happens beside the notebook                    | Notebook edits, source edits, and preview feedback stay in one workspace              | Studio workspace                                       |
| Server, browser, and static delivery share one view      | Teams can choose Python access, browser portability, or static hosting per deployment | Runtime ports and process composition roots            |
| Agents work through saved source and structured evidence | Automated edits remain inspectable and can be validated against the rendered result   | Agent API, analysis pipeline, and browser observations |

Marimo owns the process, authentication, notebook execution, reactive graph,
sessions, WebSockets, virtual files, native routes, controls, and output
renderers. Studio extends that host with view documents, projections, authoring
tools, delivery choices, and agent workflows.

## Know where the complexity comes from

The difficult code protects concrete product promises.

| Source of complexity           | Promise it protects                                                                            | Failure to avoid                                         |
| ------------------------------ | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Stable cell and value identity | A view keeps pointing at the intended notebook result as source evolves                        | A projection silently binds to another cell              |
| Coherent document revisions    | HTML, CSS, runtime configuration, and projections appear as one committed view                 | A page mixes files or bindings from different saves      |
| Explicit resource ownership    | Controls, virtual files, widgets, sessions, and patches live until their final consumer leaves | A view leaks state or tears down a shared resource early |
| Several execution environments | The same authored view can use a server kernel, a browser worker, or a static export           | Runtime state crosses an invalid serialization boundary  |
| Concurrent source writers      | Browser edits and external editor changes remain recoverable                                   | A late save overwrites newer work                        |
| Evidence-bound automation      | An agent can connect a repair to the exact view, revision, runtime, session, and request       | Diagnostics describe stale or unrelated output           |

Follow the complete maps in
[Product and workspace](development_docs/architecture/product-and-workspace.md),
[Marimo integration](development_docs/architecture/marimo-integration.md),
[Browser runtime and authoring](development_docs/architecture/browser-runtime-and-authoring.md),
and [Agents and delivery](development_docs/architecture/agents-and-delivery.md).

## Bound complexity with ports and adapters

Keep product policy on Studio-owned contracts. Put host-specific knowledge at
the edge.

1. Define Python capabilities in `_capabilities.py` and browser contracts in
   `packages/protocol` or `packages/runtime`.
2. Implement private Marimo integration in `_compat` and unstable frontend
   integration in `packages/marimo-frontend`.
3. Select adapters in `_composition.py` or a browser application composition
   root. Keep selection out of feature modules.
4. Give each stateful adapter an explicit install, attach, detach, close, or
   dispose boundary. Final-owner teardown releases the underlying resource.
5. Validate the pinned Marimo release, private layouts, generated browser
   assets, and behavior contracts at the process roots that consume them.
6. Test through the port and through the live user seam. A mock proves local
   policy. Browser acceptance proves the composed Marimo behavior.
7. Record an upstream replacement or deletion condition for every private
   capability. An upstream change should replace one adapter while product
   policy and callers remain stable.

The port should be deep enough that removing its adapter would otherwise
spread Marimo internals across policy modules. Avoid ports that have no
production caller or that mirror a private helper one method at a time.

For a cross-boundary change, trace this path before editing:

```text
user behavior
  -> durable state and owner
  -> Studio port or browser record
  -> selected adapter
  -> lifecycle boundary
  -> contract test
  -> live acceptance case
```

## Preserve dependency direction

- `_workspace` owns configuration and files. `_server` owns Studio HTTP
  policy. `_cli` adapts commands. These packages import ports, never concrete
  `_compat` modules.
- `_compat` owns private `marimo._*` imports and reversible host patches. Ruff
  enforces the Python boundary.
- `packages/protocol` owns serializable browser records and performs no I/O.
  `packages/runtime` imports protocol and performs no Marimo, React, or browser
  I/O.
- `packages/presentation` owns the authored document and projection lifecycle.
  `packages/studio` owns the editor workspace. `packages/marimo-frontend`
  quarantines unstable Marimo frontend imports.
- Studio source follows `app -> features -> shared`. Features import no app
  module. Shared primitives import no app or feature module.
- `apps/browser` composes browser entry points. `apps/e2e` owns live browser
  acceptance. `apps/docs` owns VitePress while `docs/` owns authored pages.

## Read sources of truth in order

1. `_compat/release.json` for the supported Marimo version, tag commit, and
   browser asset identity.
2. `_capabilities.py` and `_composition.py` for Python ports, selected
   providers, validation, and lifecycle.
3. `packages/protocol` for browser records and `packages/runtime` for the
   runtime SPI.
4. Runtime diagnostics and contract tests for observed behavior.
5. `development_docs/` for engineering reasoning and `docs/` for supported
   user workflows.

## Keep one mutable owner

| State                      | Owner                                   | Release boundary                   |
| -------------------------- | --------------------------------------- | ---------------------------------- |
| Notebook services          | `NotebookScopeRegistry`                 | Marimo application lifespan        |
| Session replay             | Selected session replay adapter         | Final adapter handle               |
| Source file revision       | Source editor sync controller           | Source document disposal           |
| Presentation revision      | Presentation revision controller        | Presentation disposal              |
| Projected output resources | Marimo frontend projection adapter      | Final rendered owner               |
| Save transformation        | Notebook source-transform extension     | Session detach or adapter shutdown |
| Agent analysis request     | Analysis coordinator and evidence store | Request completion or cancellation |

## Commands

| Task                 | Command           |
| -------------------- | ----------------- |
| Install              | `make install`    |
| Format               | `make format`     |
| Lint                 | `make lint`       |
| Type-check           | `make typecheck`  |
| Test                 | `make test`       |
| Browser acceptance   | `make e2e`        |
| Browser test runner  | `make e2e-ui`     |
| Local gate           | `make check`      |
| Build browser assets | `make build`      |
| Build docs           | `make docs-build` |
| Serve docs           | `make docs-serve` |
| Build distributions  | `make package`    |

Python tooling runs through `uv`. Browser and documentation tooling runs
through the pnpm workspace. Vite Plus owns formatting, linting, TypeScript
checks, tests, builds, and task execution.

## Validate the user boundary

- Run focused owner tests while working and `make check` before handoff.
- Run `make build` and `make e2e` after a change crosses Python, browser,
  document, runtime, or session boundaries.
- Use `apps/e2e` for behavior that crosses the native editor, kernel,
  filesystem, authored document, and preview.
- Build generated browser assets from workspace source. Use `make package` to
  verify wheel contents, entry points, worker chunks, and release identity.
- Inspect visible changes at desktop and narrow widths. Check console errors,
  failed requests, projections, controls, anywidgets, view switches, source
  conflicts, and external edits as the feature requires.
- Update `development_docs/` when ownership or lifecycle changes. Update
  `docs/` when the supported user capability or workflow changes.

## Route the task

| Task                                      | Guide                                                                                           |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------- |
| General contribution                      | [Contributor guide](development_docs/README.md)                                                 |
| Product model or workspace files          | [Product and workspace](development_docs/architecture/product-and-workspace.md)                 |
| Python architecture or Marimo upgrade     | [Marimo integration](development_docs/architecture/marimo-integration.md)                       |
| Frontend facade or browser lifecycle      | [Browser runtime and authoring](development_docs/architecture/browser-runtime-and-authoring.md) |
| Agent APIs, analysis, export, or delivery | [Agents and delivery](development_docs/architecture/agents-and-delivery.md)                     |
| Focused frontend workflow                 | [Frontend workspace](development_docs/frontend.md)                                              |
| Studio distribution or release            | [Releasing](development_docs/releasing.md)                                                      |
| Live cross-boundary behavior              | `apps/e2e` and the browser acceptance commands                                                  |
