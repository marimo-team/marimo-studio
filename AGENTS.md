# AGENTS.md

Marimo Studio turns one reactive notebook into named web views. The notebook
owns data, computation, controls, and domain decisions. Studio owns view
projects, provider discovery, build publication, projections, delivery, and
agent workflows.

Marimo owns process lifecycle, authentication, notebook execution, sessions,
reactivity, virtual files, controls, widgets, and native output rendering.
Keep private Marimo integration inside `_compat`.

## What the complexity buys

| Mechanism                                      | User capability                                                                                                               |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Explicit view projects and provider inspection | Each view can use its own source and build workflow while Source shows the documents relevant to that project.                |
| Immutable artifacts and distinct revisions     | A failed build keeps the current preview available, and editors, browsers, exports, and agents consume one coherent revision. |
| Symbolic projections                           | Custom layouts retain native notebook cells, values, rich outputs, controls, and dependency behavior.                         |
| Explicit owners, generations, and evidence     | View switches, reconnects, concurrent edits, and automated operations stay tied to current state.                             |
| One artifact across execution environments     | The same view can run with a Python kernel, in a browser worker, or as a static export.                                       |

## Durable boundaries

- Treat authored documents, build inputs, and public artifact files as separate
  allowlists. Persist view choices in `view.toml`. Starter identity is
  creation-time input.
- Keep document, project, artifact, and presentation identities distinct. Bind
  mutations to the owner, generation, revision, and session they observed,
  then revalidate those identities immediately before commit.
- Give connections, subscriptions, claims, processes, leases, and background
  operations explicit owners. Every claim reaches a terminal state. Release
  uncommitted work on every exit path and reject acquisitions after close
  begins.
- Provider inspection returns bounded plans. Core owns validation, persistence,
  publication, and projection authorization. Inspection is read-only.
- Treat native Marimo output subtrees as opaque. Register projections from
  artifact-authored hosts and release them when ownership changes.
- Stage source, artifact, and presentation replacements, then commit them
  atomically. A failed replacement retains the last valid state.
- Keep user-visible transitions separate. Run filesystem discovery, provider
  calls, process waits, and native observer shutdown off the event loop and
  outside mutation locks.

Dependencies point from applications and adapters toward Studio contracts.
Private Marimo APIs stay in `_compat`, provider and framework knowledge stays
in `view_providers._bundled`, and serializable browser records stay in
`packages/protocol`. Product policy must not import those details back.

Trace every cross-boundary change through:

```text
user behavior
  -> durable state and owner
  -> Studio record or port
  -> selected adapter
  -> lifecycle boundary
  -> contract test
  -> live acceptance case
```

## Evidence and validation

- Run focused owner tests while working and `make check` after source changes.
- Add `make build` and `make e2e` for browser, artifact, document, runtime, or
  session changes. Add `make package` for distribution changes. Add
  `make docs-build` plus desktop and narrow inspection for public docs.
- Test through the API, command, file, protocol, browser state, or package
  boundary that consumers use. Add cases for a distinct runtime, platform,
  input, lifecycle phase, failure, security boundary, or compatibility promise.
- Use observable readiness and owned barriers for lifecycle tests. Keep test
  resources explicit, make browser diagnostics fail closed, and avoid shipped
  routes or public records that exist to coordinate tests. Preserve the
  worktree during read-only audits.

## Canonical guidance

- [Architecture and ownership](development_docs/architecture.md)
- [Contributor workflow](development_docs/README.md)
- [Frontend workflow](development_docs/frontend.md)
- [Release workflow](development_docs/releasing.md)
- [Agent view workflow](skills/marimo-studio/SKILL.md)
