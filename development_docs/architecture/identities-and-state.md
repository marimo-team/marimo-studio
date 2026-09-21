# Identities and state

Studio accepts a mutation only when it still names the state that produced it.
Use the narrowest identity in this page and revalidate it immediately before
commit.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Decision

An identity answers one question about one owner. A revision identifies
content. A generation identifies an incarnation or ordering domain. A session
identifies one live participant. Do not pass an unqualified `revision`,
`generation`, or `session` across a package boundary.

Records that cross Python and browser code keep the field names defined in
`packages/protocol`. Internal variables should add the owner when the record
does not provide that context.

## Durable workspace identities

| Identity                 | Owner                               | Changes when                                                                                 | Used to reject                                                               |
| ------------------------ | ----------------------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Configuration generation | `_workspace`                        | The selected notebook or project configuration changes                                       | A mutation planned from older configuration                                  |
| Catalog generation       | `_workspace`                        | View membership, a view incarnation, or catalog-owned configuration changes                  | Create, remove, write, or validate work against another catalog              |
| View generation          | `_workspace`                        | One view name is created, removed, replaced, copied, or adopted with a new directory owner   | Work against an earlier project that reused the same name                    |
| Source document revision | `_views`                            | UTF-8 Source content changes                                                                 | A conditional Source save based on stale content                             |
| Notebook revision        | `_notebook`                         | Saved notebook bytes change                                                                  | Inspection, runtime validation, or execution against another saved notebook  |
| Project revision         | `_artifacts`                        | Provider identity, build fingerprint, or declared build input changes                        | Publishing a candidate built from older inputs                               |
| Artifact revision        | `_artifacts`                        | The validated browser file tree, entry document, or mount declarations change                | Serving or pinning another immutable artifact                                |
| Presentation revision    | `_server.presentation`              | The coherent artifact, notebook graph, source, configuration, or presentation record changes | Runtime configuration, browser reads, or evidence from another page snapshot |
| Projection revision      | `_delivery` and `packages/protocol` | Notebook bindings, runtime, mounts, targets, policies, or projection diagnostics change      | Reusing projected state after its authorization inputs change                |

`catalog_generation` and `view_generation` travel together on Source, create,
remove, and validation requests. A document revision cannot substitute for
either owner. The same bytes may appear in a newly created view whose view
generation is different.

`artifact_revision` is content-addressed and can be shared by the development
and production profiles. Each profile still owns its own publication pointer,
latest build attempt, and provider provenance.

## Live operation identities

| Identity                     | Owner                                 | Scope                                                             |
| ---------------------------- | ------------------------------------- | ----------------------------------------------------------------- |
| Browser client ID            | `StudioClientRegistry`                | One Studio browser identity across reconnects                     |
| Notebook source generation   | `_notebook`                           | One notebook revision plus the captured filesystem identity       |
| Native editor session ID     | Marimo session state                  | One consumer connection to a shared Python notebook session       |
| Binding generation           | `StudioClientRegistry`                | One accepted client and native-session pairing                    |
| Active-view generation       | `StudioClientRegistry`                | One committed selected view for a client                          |
| Workspace stream generation  | Browser and server event coordinators | One promoted event stream and its initial baseline                |
| Presentation session ID      | Presentation routing                  | One isolated page audience                                        |
| Runtime session ID           | Runtime and Marimo session adapters   | One Server runtime session used by a presentation                 |
| Runtime instance             | Runtime catalog                       | One mounted runtime incarnation                                   |
| Document lifecycle ID        | Presentation document                 | One loaded presentation document                                  |
| Request ID                   | Operation owner                       | One activation or query operation                                 |
| Notebook mutation generation | Native editor and Preview             | One editor document transaction in the current editor incarnation |

A `PeerTarget` captures browser client, native session, binding generation,
active view, and active-view generation. Agent work retains that complete
target until completion. A reconnect can preserve the pair while a rebind,
view handoff, or reclaimed client invalidates work from the earlier generation.

`ShowResult.generation` is the active-view generation observed when the browser
committed the requested view. Call it `active_view_generation` in surrounding
code and prose when the record field is not required.

## Projection identities

A projection crosses four distinct identities:

```text
source declaration ID
  -> mounted instance ID
  -> symbolic target and producer
  -> runtime cell ID
```

The declaration ID belongs to one provider-inspected source location. The
instance ID belongs to one connected DOM host. The symbolic producer belongs
to the saved notebook graph. The runtime cell ID belongs to one compiled or
live runtime.

Moving a connected host preserves its instance ID and resource owners. Changing
its target preserves the DOM instance ID, releases resource ownership for the
old target, and acquires ownership for the new target. Removing the host
releases its final owners.

## Prepared publication identities

`PreparedViewRequest.key` contains view, editor binding, and presentation
revision. That key selects the current publication. State-space source identity
belongs to the candidate admission check, so a rejected replacement retains
the preceding publication under the same key.

Marimo-export assigns the immutable export instance and owns its generation
lease. Studio's manifest adds view, document digest, plan digest, and projection
bindings. Current-manifest requests resolve the browser client to its editor
binding and require the presentation revision. Immutable asset requests name
the export instance and a recorded relative path.

## Build state

Each build profile stores one current publication and one latest attempt:

| Phase       | Current publication   | Meaning                                                     |
| ----------- | --------------------- | ----------------------------------------------------------- |
| `unbuilt`   | Absent                | The profile has no build receipt                            |
| `building`  | Retained when present | Provider work is active                                     |
| `published` | Present               | The latest attempt published this artifact                  |
| `stale`     | Present               | Source or recovery state moved beyond the retained artifact |
| `failed`    | Retained when present | The latest attempt failed                                   |

An interrupted `building` receipt becomes `stale` when it retains a
publication and `failed` when it does not. Readers recover that state only
after acquiring the build lock non-blocking and confirming that no build owner
remains.

## Presentation readiness

Readiness has several owners:

| State                  | Owner                            | Complete when                                                        |
| ---------------------- | -------------------------------- | -------------------------------------------------------------------- |
| Artifact published     | Artifact repository              | A validated candidate and profile receipt commit atomically          |
| Presentation committed | Presentation revision controller | Document, runtime configuration, base, and styles share one revision |
| Runtime mounted        | Runtime session                  | `mount()` resolves for the selected runtime instance                 |
| Projection ready       | Projection host                  | The mounted instance has resolved and rendered its selected result   |
| Receiver admitted      | Preview admission                | The exact document revision completes the build and refresh barriers |

Use the state that protects the caller. Runtime mount does not prove projection
readiness. Presentation commit does not prove Preview admission. The document's
`data-marimo-studio-revision` exposes its committed presentation revision.
`data-marimo-studio-state` covers Studio runtime and projection readiness.
Application behavior requires its own browser assertions.

## Mutation rule

Every cross-boundary mutation follows one sequence:

```text
capture owner and identity
  -> perform work outside the mutation lock
  -> reacquire the owning lock
  -> revalidate every captured identity
  -> commit atomically
  -> publish the new identity
```

Release staged files, process claims, leases, and browser waiters on every exit
path. A close operation rejects new acquisitions before waiting for retained
owners.

## Failure behavior

- Return a generation conflict when the named workspace or view incarnation
  changed.
- Return a source conflict with the current document revision when a Source
  save loses its comparison.
- Mark a candidate superseded when project inputs change before publication.
- Ask a presentation to refresh when its projection revision is stale.
- Reject exact preview navigation when the requested presentation revision differs.

## Contract tests

Protect identities through the boundary that consumes them:

- Recreate a view under the same name and reject its earlier handle.
- Race a Source save with an external write and preserve the unsaved buffer.
- Change a build input before publication and retain the current artifact.
- Retarget and remove projection hosts while checking resource ownership.
- Replace an event stream and ignore callbacks from its earlier generation.
- Rebind an editor session and reject earlier activation and query work.
- Reload the editor and restart notebook mutation generations from a fresh
  namespace.
