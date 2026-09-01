# Agents and delivery

Agents use one notebook-bound facade. Delivery consumes the same validated
publication as live views.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Agent API

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = await workspace.create_view(
    "dashboard",
    starter="marimo-studio/vanilla:default",
)
inspection = await view.inspect()
build = await view.build()
await view.show()
report = await view.validate(level="browser")
```

`agent` exports the notebook-bound `Workspace` and `View` interfaces.
`_authoring` owns their operations. `_browser_client` owns page selection,
observation, protocol decoding, and bounded HTTP transport.

Agents inspect the provider document catalog, then read and conditionally write
each editable document through `View.read()` and `View.write()`. The expected
source revision prevents a late save from replacing newer work.

## CLI parity

The CLI uses the same application services:

```text
status
notebook inspect/bind
starters
view create/inspect/read/write/build/show/export/remove
validate --level static|runtime|browser
doctor
```

JSON data uses stdout. Progress and diagnostics use stderr. Validation failure,
configuration failure, and live connection failure have distinct exit codes.

Read [Provider environments](provider-environments.md) for CLI re-entry and
[Errors and diagnostics](errors-and-diagnostics.md) for exit codes, JSON Lines,
HTTP translation, browser diagnostics, and validation issues.

## Browser clients

The server assigns each Studio browser a client identity and a native editor
session. A client-scoped capability signs that exact pair. Activation and
observation requests select one browser. When selection is ambiguous, the
caller supplies a client ID.

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

The agent coordinator owns pending activation and observation operations. An
activation records client, session, binding generation, active-view generation,
and requested view. An observation also records runtime, runtime instance,
presentation revision, request ID, and expected active-view generation.

One browser handles one agent operation at a time. Request cancellation clears
the pending operation and releases its waiter. Active-view handoff cancellation
uses its rollback and authoritative stream-recovery path.

## Validation

Validation is cumulative:

- Static reads saved notebook and view source.
- Runtime starts the complete reactive notebook in an isolated process, then
  checks the selected projected results.
- Browser observes the active rendered presentation.

A validation issue includes stage, severity, stable code, message, advice, and
available view, target, or source evidence. Browser facts are accepted only for
the requested client, binding and runtime sessions, view, runtime, runtime
instance, presentation revision, request ID, increasing sequence, and validated
projection instances.

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
compatible notebook in a browser worker. Both consume the same artifact
document and symbolic target grammar.

## Static export

Export:

1. Selects or builds the production publication.
2. Copies its complete browser file tree.
3. Adds the packaged runtime and notebook source.
4. Writes the destination through a staging directory.
5. Atomically installs the completed export.

The returned entrypoint may be nested. Artifact-relative assets remain beside
the provider document.

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
