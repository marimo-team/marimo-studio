# Contributor guide

Marimo Studio lets one Marimo notebook back multiple custom web views. Its
authoring workspace keeps the notebook, view source, and live preview together.
When making a change, start with the behavior users rely on, update the code
responsible for it, and test that behavior in the working product.

## Understand the product boundary

Marimo owns notebook execution, the reactive graph, sessions, authentication,
WebSockets, virtual files, native routes, output renderers, controls, and
widgets. Studio owns named view documents, projections into those documents,
the notebook and view authoring workspace, runtime selection, agent evidence,
and static packaging.

Read [Architecture](architecture.md) before a change crosses one of these
boundaries. Its four detailed maps connect every major subsystem to the user
feature that pays for its complexity:

| Change area                                                                        | Architecture map                                                               |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Configuration, views, aliases, source revisions, or transactions                   | [Product model and workspace](architecture/product-and-workspace.md)           |
| Marimo routes, sessions, saves, kernels, private APIs, or upgrades                 | [Marimo integration](architecture/marimo-integration.md)                       |
| Browser protocol, runtimes, projections, source editor, layout, or frontend facade | [Browser runtime and authoring](architecture/browser-runtime-and-authoring.md) |
| Agents, CLI, process supervision, ASGI, export, E2E, docs, or packaging            | [Agents and delivery](architecture/agents-and-delivery.md)                     |

Use [Frontend workspace](frontend.md) for package commands and the Marimo
frontend source workflow. Use [Releasing](releasing.md) for versioning,
publication, and recovery.

## Install the workspace

Install the locked Python and JavaScript environments:

```console
make install
```

Python tooling runs through `uv`. Browser and documentation tooling runs
through the pnpm workspace, where Vite Plus owns formatting, linting,
TypeScript checks, tests, builds, and task execution.

## Work in one owning slice

Use the smallest loop that proves the changed contract:

| Owner                       | Focused loop                                                |
| --------------------------- | ----------------------------------------------------------- |
| Python workspace or service | `uv run pytest packages/marimo-studio/tests/<test-file>.py` |
| Protocol                    | `pnpm --filter @marimo-studio/protocol test`                |
| Runtime SPI                 | `pnpm --filter @marimo-studio/runtime test`                 |
| Presentation document       | `pnpm --filter @marimo-studio/presentation test`            |
| Studio workspace            | `pnpm --filter @marimo-studio/studio test`                  |
| Marimo frontend facade      | `pnpm --filter @marimo-studio/marimo-frontend test`         |
| Documentation               | `make docs-build`                                           |

Keep tests with the owner of the contract. Add a browser acceptance case under
`apps/e2e` when the result crosses the native editor, kernel, filesystem,
session, worker, or preview documents.

## Change a boundary deliberately

1. State the user-visible result and the identity or state that must survive.
2. Find the semantic owner in the architecture maps.
3. Add local behavior to that owner.
4. Cross packages with a protocol record, runtime interface, feature port, or
   closeable handle.
5. Cross into private Marimo behavior through `_capabilities.py`,
   `_composition.py`, and one `_compat` or `packages/marimo-frontend` adapter.
6. Update producer, consumer, diagnostic, and contract tests together when a
   boundary shape changes.
7. Add live acceptance when the product promise depends on lifecycle ordering
   or several documents and processes.

Studio source follows these enforced dependency directions:

```text
Python policy -> Studio-owned capability ports -> _compat adapters -> Marimo

apps/browser -> presentation -> runtime -> protocol
             -> studio -----------------> protocol
presentation -> marimo-frontend --------> Marimo frontend

Studio app -> features -> shared
```

## Finish at the consumer boundary

Run the repository gate:

```console
make check
```

Add the matching boundary checks:

| Change                                                                            | Additional check                                             |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Browser package, protocol, runtime, or Marimo frontend adapter                    | `make build`                                                 |
| Session, frame, source, projection, control, query, view, or responsive lifecycle | `make e2e`                                                   |
| Generated browser assets or distribution contents                                 | `make package`                                               |
| Public documentation                                                              | `make docs-build` and rendered desktop and narrow inspection |

`make check` checks formatting, linting, types, tests, examples, runtime checks,
and package-owned contracts. It does not replace live browser acceptance for a
cross-document behavior.

## Keep authored and generated files distinct

Edit source under `packages/`, `apps/`, `docs/`, `development_docs/`,
`examples/`, and `skills/`.

`make build` prepares the pinned Marimo frontend and writes browser assets to:

```text
packages/marimo-studio/src/marimo_studio/_static/browser/
```

The prepared Marimo checkout lives under
`packages/marimo-frontend/.cache/`. Both paths are generated and remain
untracked. Change their owning source and rebuild them through the repository
commands.

## Keep documentation paired with behavior

Update the surface that owns the reader's question:

| Reader                                      | Source                                                         |
| ------------------------------------------- | -------------------------------------------------------------- |
| Product user completing a task              | `docs/guide/`                                                  |
| User looking up an exact contract           | `docs/reference/`                                              |
| Contributor changing ownership or lifecycle | `development_docs/architecture/`                               |
| Contributor running a package workflow      | `development_docs/README.md`, `frontend.md`, or `releasing.md` |
| Coding agent following the authoring loop   | `skills/marimo-studio/` and the public agent guide             |

Public docs explain the capability and user consequence. Development docs
explain the owners, invariants, compatibility seams, lifecycle, and validation
that make the capability work.
