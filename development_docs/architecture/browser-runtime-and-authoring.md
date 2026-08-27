# Browser runtime and authoring

The browser composes two documents. The native Marimo editor remains the
notebook surface. A Studio presentation document renders one immutable view
artifact with a selected runtime. The Studio workspace arranges Notebook,
Source, and Preview surfaces around those documents.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Package ownership

| Package                    | Owns                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------- |
| `packages/protocol`        | Zod schemas and inferred transport records                                              |
| `packages/runtime`         | Runtime registration, mount, update, control, query, and disposal SPI                   |
| `packages/presentation`    | Artifact document, revision transaction, projections, styles, navigation, and readiness |
| `packages/studio`          | Notebook, Source, Preview, view inventory, and workspace controllers                    |
| `packages/marimo-frontend` | Named adapters around unstable Marimo frontend modules                                  |
| `apps/browser`             | Final browser composition                                                               |
| `apps/e2e`                 | Live Marimo and Chromium acceptance                                                     |

Protocol performs no I/O. Runtime imports protocol and performs no Marimo,
React, or browser I/O. Presentation imports runtime, protocol, and named Marimo
frontend adapters. Studio imports protocol and stays independent of
presentation implementation.

Within Studio, source follows `app -> features -> shared`. Feature slices
import no app module. Shared primitives import no app or feature module.

## Browser documents

```text
Marimo editor document
  owns notebook editing and live session

Studio workspace document
  owns navigation, panes, Source, and preview frames

Presentation document
  owns one artifact shell and projection hosts
```

The workspace keeps a bounded cache of preview frames keyed by runtime and
view. Frames remain mounted while the user changes workspace modes so runtime
state survives pane rearrangement, view switching, and runtime switching.

## Runtime document assembly

`render_presentation_document()` starts from the artifact entry document and
injects Studio runtime assets, support URL, presentation revision, selected
runtime, notebook filename, and development flags.

The authored document must contain one complete `head`, one complete `body`,
and one `#app-shell`. Studio owns runtime markup around that shell.

The document base points at the selected artifact revision. Relative scripts,
styles, dynamic imports, images, fonts, workers, and local fetches resolve
inside one immutable public file tree.

Runtime configuration carries:

- Presentation revision, projection revision, and selected view
- Available and selected runtime
- Runtime-specific connection or worker data
- Precomputed projection targets and dependency closures
- Artifact mount declarations
- Projection policy and semantic-to-runtime cell bindings
- Projection diagnostics
- Marimo app, user, and override configuration
- Development and mode state

`_delivery/runtime_config.py` serializes this record for live Server and static
export delivery. The shared JSON fixture is parsed by the Zod protocol tests.

The presentation revision identifies the exact page snapshot used for browser
requests and evidence. The projection revision identifies the notebook,
runtime, mounts, targets, bindings, policy, and diagnostics that own projected
state. A stylesheet or non-projection markup edit advances the presentation
revision while retaining live values, outputs, controls, and cell portals.

## Presentation revision transaction

`PresentationRevisionController` owns the browser transaction that replaces an
artifact document, runtime configuration, styles, or selected view.

```text
begin readiness generation
  -> cancel prior transition
  -> fetch candidate document
  -> read presentation revision
  -> fetch matching runtime configuration
  -> parse candidate document
  -> prepare projection hosts
  -> stage view styles and linked stylesheets
  -> commit support URL and runtime configuration
  -> update authored markup around stable projection hosts
  -> reload when projection host placement changes
  -> commit styles and document base
  -> mark ready
```

Failure discards staged state and keeps the current document mounted. A script
change that requires browser evaluation triggers a full document reload. A
runtime-only change updates runtime configuration. A stylesheet-only artifact
change can refresh linked styles while preserving the shell.

The controller owns cancellation, rollback, readiness, and failure diagnostics
as one transaction. `BrowserSessionReplay` owns browser-side server-session
replay state and gives the controller preserved reload URLs and session memory
through a narrow port.

## Projection host runtime

`ProjectionHostRuntime` registers and coordinates three host families:

- `<marimo-cell name="...">`
- `<marimo-output value="...">`
- Elements carrying `mo-value="..."`

Each artifact host carries a provider-injected source-site ID. The runtime
assigns an instance ID when the host connects, resolves its current target,
and releases ownership when the host disconnects or changes targets.

Host adapters participate in:

- Custom-element registration
- Candidate document preparation
- Source-site and target observation
- Mount and disconnect
- Preservation across document swaps
- Readiness contribution
- Projection-instance observations

Read [Symbolic projections](symbolic-projections.md) for authorization,
resolution, duplicate ownership, quotas, and evidence.

## Runtime SPI

`packages/runtime` defines one runtime lifecycle shared by Server and
WebAssembly:

```text
register
  -> mount
  -> configure
  -> attach projection instances
  -> synchronize controls and query
  -> update presentation
  -> dispose
```

### Server

The Server runtime connects projection instances to one existing Marimo
session. It maps semantic `CellRef` values to live runtime cell IDs, reads
values through the kernel host, renders rich outputs, and relays controls and
query state.

### WebAssembly

The WebAssembly runtime starts a browser worker from saved notebook source and
the pinned Marimo frontend. It instantiates the notebook graph, executes the
projection bootstrap cell, and keeps automatic notebook execution disabled.
Studio resolves each mounted host to a semantic producer and dependency
closure, then submits the required cells through Marimo's serialized execution
queue. A target change schedules newly required cells. An unmount cancels work
that is still waiting for its queue slot.

The worker instance and executed cells survive artifact and site revisions
whose runtime instance remains unchanged. Independent notebook branches stay
dormant until a mounted target resolves to them.

Runtime providers return one `RuntimeProjection` with instance identity,
runtime data, and semantic cell bindings. The browser commits runtime
configuration before attaching projection hosts.

## Studio workspace model

The workspace has three surfaces:

| Surface  | Content                               |
| -------- | ------------------------------------- |
| Notebook | Native Marimo editor frame            |
| Source   | Provider-discovered project documents |
| Preview  | Selected artifact and runtime frame   |

Notebook, Develop, and Preview form the primary mode navigation. Source is an
additional selectable mode in the workspace menu:

- Notebook
- Develop
- Preview
- Source

Develop shows Notebook, Source, and Preview. A newly created view uses the authoring
layout with Notebook beside stacked Source and Preview. Source shows Source and
Preview. The **Open saved layout** workspace action restores the persisted layout,
which can place any surface beside another.

`LayoutController` owns layout trees, pane placement, split ratios, compact
state, per-view persistence, and arranging. The render layer reads controller
snapshots and performs no layout policy.

## Dynamic Source catalog

The Source feature receives a `ViewProject` browser record from the project
endpoint. The record contains provider, documents, diagnostics, and
published artifact state.

One horizontally scrollable tab strip displays `SourceDocumentSpec` order.
Each tab exposes:

- Project-relative path
- Provider language ID
- Edit or read access
- Loaded, saving, external, conflict, or error state
- Source-located provider or build diagnostic

The full relative path is the accessible name and tooltip. A provider label
can supply compact visible text.

Keyboard behavior:

- Left and Right select adjacent tabs.
- Home selects the first document.
- End selects the final document.
- The selected tab scrolls into view.
- `Cmd+S` and `Ctrl+S` save an editable document.

The controller remembers one active path per view. It selects the first
editable document when the stored path disappears, then falls back to the
first document.

## Editor languages

`SourceEditor` accepts provider language IDs. The shipped CodeMirror modes load
on demand for:

- HTML
- CSS
- JavaScript
- TypeScript
- JSX
- TSX

JSON, Markdown, Svelte, text, TOML, XML, and unknown language IDs use plain
text. Read-only documents support navigation, selection, search, and copy while
suppressing edits and saves.

Language support is presentation policy. Providers report language IDs and
remain independent of CodeMirror.

## Source synchronization

`SyncedSource` owns one document buffer and revision:

```text
load with ETag
  -> edit
  -> debounce
  -> PUT with If-Match
  -> commit new ETag
```

An external change triggers a read. Clean buffers accept disk content. Dirty
buffers compare local and remote content and enter conflict state when the
contents differ.

Conflict actions are:

- Use disk content and revision.
- Keep local content and save against the acknowledged remote revision.

The Source controller keeps pending or conflicted buffers visible when a
provider catalog changes. It disposes clean buffers that leave the catalog.

## Native editor session

The Studio host assigns one browser client ID and one native editor session,
then signs the pair for the notebook, base URL, edit mode, and server instance.
`StudioClientRegistry` retains one live session per client and one client per
session. Reconnecting the same pair is idempotent. A live client or session
presented with another partner fails before native connection.

An editor-root reload may omit `session_id`. The server resolves the session
from the retained client binding and returns a no-store redirect to the same
session. The registry gives an accepted pair a `SessionBindingLease`. Native
connector admission checks that lease again before attaching to an existing
session or creating a fresh one. Binding rejection and disconnect-grace
reclamation invalidate the lease, so delayed connector work cannot claim stale
authority.

## View switching

`ViewTransition` commits the latest requested view after current authoring state
is safe to leave:

```text
flush current editable documents
  -> synchronize authored query state
  -> select the verified publication in preview frames
  -> commit route and layout
  -> inspect the selected ViewProject
  -> load its active Source document
  -> refresh when validation publishes another revision
```

A failed save or unresolved conflict stops the transition before preview state
changes. Target inspection and source-read failures remain attached to the
selected Source session. A newer selection cancels an older in-flight
transition.

A browser-owned selection stages the preview, then acquires an active-view
handoff before committing `ViewController.current`. The handoff makes the
browser unavailable to agent work during the commit gap. Rollback restores the
previous preview and releases the same handoff operation. When release cannot
be confirmed, `WorkspaceEventCoordinator` reconnects a higher-generation
stream for the still-committed view and waits for its authoritative baseline.

Reactivating the current view can reload prepared runtime frames while
preserving the view and workspace selection.

## Workspace events

The `change` event has four kinds:

- `project` carries source changes to the Source controller.
- `build` asks Source to reconcile provider diagnostics and build state. Build
  records use `unbuilt`, `building`, `published`, `stale`, or `failed`.
- `presentation` asks Source to reconcile and tells Preview that a new
  presentation revision is available.
- `views` refreshes the view inventory.

The initial `ready` event refreshes inventory, reconciles Source, and gives
Preview its presentation baseline. Separate `activate`, `observe`, and
`session` events carry agent requests and editor session bindings.

The event URL carries a client-scoped capability signed for the notebook, base
URL, edit mode, and server instance. The server validates the capability,
client, stream generation, and active view before reserving client state.

Stream replacement has two phases on both sides. The server reserves a
candidate lease while it prepares the source subscription and presentation
baseline, then promotes the highest valid generation before sending `ready`.
The browser keeps the current `EventSource` authoritative until the candidate
sends `ready`, then installs its baseline and closes the previous stream.
Callbacks from stale generations cannot change workspace state.

## Preview deck

`PreviewDeck` owns stable physical slots and resolves them by `(runtime, view)`.
Server has three least-recently-used slots. WebAssembly has one. Returning to a
warm key reuses its iframe, document, runtime instance, controller, navigation,
and diagnostics. Eviction disposes the controller and resets the iframe.

Each occupied slot owns one `PreviewController`. Its `PreviewAdmission` is the
authoritative owner of receiver identity, candidate and ready identity,
presentation baseline, build barrier, refresh handshake, admitted revision,
and view phase. Readiness requires the exact receiver revision to match the
admitted ready revision after the build and refresh gates settle. Reactivating
a warm slot revokes cached readiness until that handshake completes.

The deck also coordinates:

- Current view and runtime
- Document and support URLs
- Presentation revision
- Projection revision
- Runtime status and diagnostics
- Editor session binding
- Presentation build and revision baseline
- Query and control synchronization
- Browser observation requests

Inactive controllers keep reconciling revision state while active side effects,
controls, query writes, retries, and observations stay with the selected slot.

## Query synchronization

`PreviewQueryController` assigns every editor mutation an operation ID and a
page-global `writeGeneration`. Retries keep the same identity. A new controller
continues above the page's previous generation.

The server claims the operation against the current browser client, Marimo
session, and binding generation. It marks lower write generations superseded,
rejects conflicting identities, and acquires one active mutation fence before
calling the kernel. Each mutation fence is keyed by client ID, native session
ID, and binding generation. Binding rejection waits for the current lease's
fence. A new native incarnation rotates the binding generation and receives an
independent fence. Closing or settling an older incarnation releases work by
its old key, so it cannot block or cancel the current lease. Server commit
revalidates the exact binding identity.

The kernel command carries a server signature over the notebook, session,
operation, query fingerprint, binding generation, write generation, and
deadline. The kernel independently verifies that identity and returns
`applied`, `superseded`, or `expired`. Its generation order and the server's
binding revalidation prevent late or retried writes from committing against a
newer editor binding.

## Navigation

Authored links can navigate within one artifact, change query or hash state, or
select another named view. The presentation adapter resolves links against the
artifact-qualified document base and delegates named view changes to Studio.

For a named view link, Studio flushes current edits and synchronizes the target
query before committing the view, query, and hash to browser history. Preview
selects the verified publication while Source hydrates the target catalog.

Browser history stores canonical public view URLs. `BrowserSessionReplay`
indexes a native Server session by file key, page path, and the canonical public
query recorded when the session is first remembered. Canonicalization sorts
public keys, retains repeated values in request order, and excludes private
routing keys. Reload and direct document navigation offer the session when the
target has that query. The replay marker and session parameter leave the
visible URL after the runtime opens.

`PrivateSessionReplay` owns the reversible Marimo server patch and the
application's registered notebook sessions. The application lifespan installs
and closes that owner. Server replay admission independently compares the
request's canonical public query with the native session's creation metadata.
Unavailable, invalid, or mismatched metadata fails the match, so the redirect
allocates a fresh presentation and runtime pair. An admitted session remains
bound to the notebook, view, presentation session, and runtime session.

## Readiness and diagnostics

Presentation readiness combines:

- Artifact document transition
- Runtime configuration
- Runtime mount
- Projection instances
- Style generation
- Current browser diagnostics

A presentation reaches ready when the current revision has committed and each
mounted projection instance is healthy. Runtime failures describe mounted
instances.

Diagnostics include view, runtime, revision, scope, source location, target,
and recovery hint where available.

## Responsive behavior

Each surface has a minimum usable size. When the saved layout exceeds the
available bounds, Studio switches to a compact single-surface presentation and
keeps the selected surface in stored state.

Validate desktop and narrow layouts for:

- Source tab overflow and selected-tab visibility
- Read-only badges and diagnostics
- Pane resizing and divider keyboard behavior
- Preview and editor frame sizing
- Compact surface navigation
- Long paths and provider names
- Conflict controls

## Test the boundary

Test browser behavior at three levels:

1. Pure model, parser, and controller tests.
2. Composed document, runtime, or workspace tests.
3. Live Server and WebAssembly acceptance.

Required cross-boundary cases include dynamic source catalogs, read-only
documents, external conflicts, failed builds with a retained preview, artifact
revision transitions, React and Svelte projection instances, runtime
switching, view switching, session reconnect, query and control synchronization,
closure-selected WebAssembly execution, static-export branch isolation, and
desktop and narrow layout inspection.
