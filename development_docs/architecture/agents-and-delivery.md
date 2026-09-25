# Agents and delivery

Agents use one notebook-bound facade. Delivery consumes the same validated
publication as live views.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Agent API

`agent_plugins.read("marimo-studio")` owns the installed briefing. Lazy module
help delegates to that reader. `marimo_studio.agent.skill()` returns the core
skill and task references, and `plugin()` returns the complete installed bundle.
These discovery operations are passive. The core skill owns the cross-provider
authoring workflow, references own conditional detail, and each view's
`AGENTS.md` owns its provider and project conventions.

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = await workspace.create_view(
    "dashboard",
    starter="marimo-studio/vanilla:default",
)
inspection = await view.inspect()
build = await view.build()
```

Acquire workspace and view handles again in each code-mode execution. After
building, use a separate execution to show the view and get its browser URL:

```python
import marimo_studio.agent as studio_agent

view = studio_agent.current_workspace().view("dashboard")
await view.show()
url = await view.preview_url(runtime="server")
```

Saved-source inspection, isolated runtime inspection, live kernel values, and
browser presentation are distinct evidence. Inheriting the saved workspace API
does not make `inspect_notebook()` a live-kernel snapshot.

`agent` exports the notebook-bound `Workspace` and `View` interfaces.
`_authoring` owns their operations. `_browser_client` owns Studio page selection,
protocol decoding, and bounded HTTP transport. Browser tools open the public
preview URL and own their waits, assertions, and captured evidence.

Agents edit source through native filesystem tools or conditionally replace
catalog documents through `View.read()` and `View.write()`. The expected source
revision protects guarded writes from replacing a newer save. Both paths feed
provider inspection, immutable build snapshots, and final publication checks.

`View.inspect()` captures the project root and owner, observed file revisions,
current project revision, published project revision, and latest build attempt.
The retained successful artifact remains distinct from a failed attempt.
`changes_since()` compares complete inventories belonging to the same view
owner. Discovery failures expose diagnostics and incomplete inventories so an
agent can repair the manifest or provider input and inspect again.

`View.hold_publication()` records an owner, token, view generation, and finite
expiry outside the editable project. Publication checks the hold across
processes under the view mutation lock. Source editing continues. Release or
expiry permits current source to reconcile through the normal build pipeline.
A hold coordinates publication through multi-file edits. It provides neither
filesystem write atomicity nor exclusion between external writers.

Checkpoint recovery uses retained `ViewDocument` content. A restore reads the
current source and writes against its current revision after review. Artifact
retention and source restoration have separate owners and effects.

## CLI parity

The CLI uses the same application services:

```text
status
notebook inspect/bind
starters
view create/inspect/read/write/hold/release/build/show/preview/preflight/export/remove
validate --level static|runtime
doctor
```

JSON data uses stdout. Progress and diagnostics use stderr. Export progress
wraps marimo-export preparation events unchanged and adds Studio build,
preflight, and commit steps. Re-entry relays both event owners. Validation
failure, configuration failure, and live connection failure have distinct exit
codes.

Read [Provider environments](provider-environments.md) for CLI re-entry and
[Errors and diagnostics](errors-and-diagnostics.md) for exit codes, JSON Lines,
HTTP translation, browser diagnostics, and validation issues.

## Browser clients

The server assigns each Studio browser a client identity and a native editor
session. A client-scoped capability signs that exact pair. Activation requests
select one browser. When selection is ambiguous, the caller supplies a client ID.

`StudioClientRegistry` owns presence, promoted workspace streams, editor-session
binding leases, active-view identity, and handoffs. It retains one live session
per client and one client per session. The same pair reconnects idempotently,
including an editor-root reload whose missing `session_id` is restored by the
server. Conflicting live pairs fail closed.

Each `PeerTarget` captures client ID, session ID, binding generation, active
view, and active-view generation. Agent operations retain that target for their
full lifetime. A same-pair reconnect can resume pending work during the
disconnect grace. Binding rejection or client reclamation invalidates the
lease. Work holding that older generation becomes `REBOUND`, while discarded
clients become `UNAVAILABLE`. A fresh pair can bind after that authoritative
release.

Browser-owned view selection acquires an operation-scoped handoff before the
view commit. While it is active, the registry reports the target as
`UNAVAILABLE`. Destination-stream promotion commits the new active view and
ends the handoff. Rollback releases the same operation ID and restores target
availability. Completed, rolled-back, and abandoned operation IDs remain as a
bounded per-client terminal tombstone set. Late acquisition and release retries
remain idempotent while that client record owns them.

The agent coordinator owns pending activation operations. An activation records
client, session, binding generation, active-view generation, and requested view.

One browser handles one agent operation at a time. Request cancellation clears
the pending operation and releases its waiter. Active-view handoff cancellation
uses its rollback and authoritative stream-recovery path.

## Validation

Validation is cumulative:

- Static reads saved notebook and view source.
- Runtime starts the complete reactive notebook in an isolated process, then
  checks the selected projected results.

Static validation captures source revisions with their provider inspections,
uses those inspections for mount checks and build preparation, then compares
fresh source and inspection records after presentation publication. Builds
inspect their immutable snapshots before producing candidates. A concurrent
notebook or view edit returns a stale-source issue at every validation level.

A validation issue includes stage, severity, stable code, message, advice, and
available view, target, or source evidence.

## Browser inspection

`View.preview_url(runtime=..., exact=False)` returns the public unframed view
URL. Saved-workspace calls provide `server`. Code-mode calls can infer it from
the current Studio connection. Runtime selection is explicit. Exact URLs carry
the current presentation revision. Resolving and navigating an exact URL both
require a current published build, and navigation rejects a different revision.

The presentation document exposes `data-marimo-studio-state` for Studio's
runtime and projection lifecycle, and `data-marimo-studio-revision` for the
committed presentation. Revision changes at the presentation commit boundary.
A failed replacement retains the previous committed revision. These values
serve ordinary DOM queries and browser predicates.

Agents finish code-mode execution before waiting on the browser, so notebook
execution can proceed. Browser tools own tab selection, waits, screenshots,
console and network inspection, and application assertions. Application code
uses normal framework lifecycles and accessible loading and error states.
Source freshness remains in `View.inspect()`.

## Server delivery

`create_asgi_app()` composes Studio middleware with Marimo's application. Run
mode serves the default and named views, runtime configuration, projections,
controls, and immutable artifact files.

Read [Server routing and security](server-routing-and-security.md) for route
ownership, authentication, capabilities, iframe isolation, and session
admission.

The returned application owns the mounted notebook from ASGI startup through
shutdown. Shutdown closes the notebook's native sessions and Studio scopes
before releasing the adapter bundle.

The Server runtime keeps Python access. The WebAssembly runtime executes a
compatible notebook in a browser worker. Edit-mode Prepared preview captures
finite states from the editor session and serves their results. These runtimes
consume the same artifact document and symbolic target grammar. Prepared live
publication and refresh ownership are described in [Marimo
integration](marimo-integration.md#prepared-preview-publication).

## Static export

`View.export()` and `view export` default to Prepared (`zero-python`). Select
`wasm` to run compatible Python in a browser worker. Prepared delivery packages
captured states, their representations, and Studio's native browser renderer.

Export:

1. Selects or builds the production publication.
2. Copies its complete browser file tree.
3. Adds either a prepared result publication or the WebAssembly runtime and
   notebook source.
4. Writes the destination through a staging directory.
5. Checks projection portability and local browser references in that exact
   staged tree.
6. Atomically installs the completed export.

The returned entrypoint may be nested. Artifact-relative assets remain beside
the provider document. `View.preflight()` runs the same build, preparation, and
staged-tree checks in a temporary directory.

### Prepared reuse dependency blocker

marimo-export currently keys prepared states by the complete notebook document,
producer environment, and output plan. A control-label edit changes that identity
and walks the state space again, even for an unchanged projected metric.
Marimo's cell cache can still restore analytical computation during that walk.

Reusing analytical states across presentation-only notebook edits requires a
marimo-export public contract for dependency-scoped execution identity and
presentation metadata refresh. It must publish current source provenance,
refresh native controls, and invalidate results that inspect changed metadata.
Studio must not substitute an older document digest or relabel an old publication.
Until that contract exists, keep independent presentation copy in view source.

## Packaging

The wheel contains Python services, provider entry points, starter resources,
browser assets, runtime worker chunks, and the packaged agent skill.

`make package` builds the wheel and source distribution, rebuilds a wheel from
the source distribution, and verifies imports, entry points, resources, and
installed commands. Example validation builds temporary source copies and reads
artifacts through production APIs.

Live acceptance covers:

- one-file view creation and editing
- failed build recovery
- two-browser source conflicts
- warm cached view switching without a document navigation
- installed external provider discovery and mount
- server and browser-worker projection parity
