# Server routing and security

`PresentationMiddleware` selects Studio routes after Marimo has supplied a
base URL, mode, notebook location, and authentication state. `StudioRoutePolicy`
selects the owner of edit-mode `/` when the middleware is composed. Requests
outside Studio's route space continue to Marimo unchanged.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities and [Identities and state](identities-and-state.md) for the
identities bound into capabilities.

## Decision

Marimo owns process authentication, notebook sessions, WebSockets, virtual
files, and native editor routes. Studio owns named view documents, immutable
artifact routes, Source and authoring routes, runtime support routes, and the
trusted wrapper around provider-authored pages.

The outer host owns initial-surface navigation. The default route policy gives
edit `/` to Studio. The explicit-host policy delegates edit `/` to Marimo and
keeps `/studio/` as the Studio authoring entry.

Route recognition is read-only. Handlers acquire notebook scopes, sessions,
leases, and mutation owners after a path, mode, method, authentication state,
and signed capability have selected one operation.

## Dispatch order

Requests pass through these decisions:

```text
ASGI scope
  -> Marimo base URL and mode
  -> edit-root route policy
  -> signed presentation capability
  -> native editor delegation
  -> Studio static runtime assets
  -> Marimo read authentication
  -> notebook location
  -> Studio route recognition
  -> workspace lifecycle
  -> ready or repair handler
```

The explicit-host policy delegates edit `/` before capability resolution,
notebook location, or notebook-scope allocation. The middleware also delegates
when Marimo cannot resolve a notebook, the mode is unknown, the path belongs to
a native route, or Studio cannot prove ownership of the requested route.

## Workspace lifecycle

Every routed notebook resolves to one state:

| State                   | Record         | Edit-mode response                                                                                                  | Run-mode response                       |
| ----------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Unconfigured            | `Unconfigured` | `/`: Studio-hosted native editor (`studio`) or native Marimo editor (`marimo`). `/studio/`: first-view application. | Marimo route or configuration error     |
| Configured with no view | `NeedsView`    | First-view application                                                                                              | `workspace-not-initialized`             |
| Ready                   | `Ready`        | Studio, Source, Preview, and support routes                                                                         | Default or named presentation           |
| Invalid                 | `Invalid`      | Repair document and structured support errors                                                                       | Structured or plain configuration error |

`WorkspaceLifecycleResolver` coalesces filesystem resolution off the event
loop. Shutdown cancels the current resolution task and closes the notebook
scope.

## Route ownership

| Route family                                      | Owner                           | Authority                                                                 |
| ------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------- |
| `/studio/` and `/studio/<view>/`                  | Studio authoring document       | Edit mode and Marimo read access                                          |
| Edit-mode `/`                                     | Studio or native Marimo         | Composition-time `StudioRoutePolicy` and Marimo authentication            |
| `/<view>/` and run-mode `/`                       | Presentation delivery           | Marimo read access plus presentation session assignment                   |
| `/<view>/_marimo-studio/artifacts/<revision>/...` | Artifact server                 | Read access or matching revision capability plus artifact lease           |
| `/_marimo-studio/views/<view>/...`                | Support router                  | Route-specific read, edit, server-token, client, and revision checks      |
| `/_marimo-studio/editor/...`                      | Native editor bridge            | Edit access plus client and session binding capability                    |
| `/_marimo-studio/presentation/<capability>/...`   | Presentation capability handler | Signed target, method, view, revision, artifact, and session audience     |
| Marimo native routes                              | Original ASGI application       | Marimo policy, optionally narrowed by an accepted presentation capability |

View names exclude Studio and Marimo route roots. Artifact public paths exclude
`_marimo-studio`, `@file`, `public`, and `public-files-sw.js` as their first
component.

## Authentication and mutation authority

Marimo places `read` and `edit` scopes on the ASGI request. Presentation
documents, immutable assets, and the Studio shell require read access.
Authoring mutations and the native editor bridge require edit access.

Studio mutation routes also compare `Marimo-Server-Token` with the
process-bound server token. The token proves that the request belongs to the
current Marimo server process. Browser client, native editor session, catalog,
view, source, and presentation identities narrow the individual operation.

An access token in the query triggers a redirect through Marimo authentication
before Studio serves a document. Structured support requests receive
`authentication-required` when read access is absent.

## Host entry

The installed entry point reads `MARIMO_STUDIO_EDIT_ROOT` once and constructs a
`StudioRoutePolicy`. `studio` preserves automatic Studio entry. `marimo`
delegates edit `/` and leaves run-mode routing unchanged. Programmatic
middleware composition receives the same immutable policy record.

Host entry validates the signed session, notebook owner, and canonical public
query before native Marimo resumes an existing session. Native, Studio,
handoff, and repair documents receive the configured `frame-ancestors` policy.

[Product and workspace](product-and-workspace.md#first-save) owns first-view and
first-save behavior. [Browser runtime and authoring](browser-runtime-and-authoring.md#native-editor-session)
owns browser-client transfer and `NativeSessionAdmission`.

## Presentation capabilities

Provider-authored pages receive two signed capability forms:

| Capability | Bound identity                                                                 | Allowed work                                                                            |
| ---------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Renewal    | Notebook file key, mode, base URL, view, presentation session, runtime session | Fetch the current document and runtime configuration                                    |
| Revision   | Renewal identity plus presentation revision and artifact revision              | Read exact assets, values, outputs, runtime support, and admitted native session routes |

The handler validates the signature, target, method, scope type, view,
presentation session header, runtime mode, and runtime-session assignment.
Revision-bound value and output requests receive a transient
`stale-projection-binding` response when the page needs refreshed bindings.
Other stale or invalid capabilities fail closed.

The capability target allowlist admits immutable artifact files, runtime
assets, configuration, projection reads, development events, selected native
reads, and the native kernel operations required by projected controls. Native
POST bodies are bounded before delegation.

### Prepared publications

Prepared support routes live under
`/_marimo-studio/views/<view>/zero-python/`. `current` resolves the browser
client to its editor binding and selects the publication for the requested
presentation revision. Edit-authorized reads can request a background refresh.
The current manifest remains available if that refresh fails.

Immutable asset URLs contain an export instance and a relative path. Studio
validates route identity and presentation authority. Marimo-export validates
asset membership and retains the generation through the response lifetime.
Studio preserves routing query parameters when deriving asset URLs from a
signed manifest URL.

## Browser isolation

The trusted wrapper loads provider-authored content in an iframe whose sandbox
permits scripts, forms, downloads, modals, pointer lock, and popups. The iframe
has an opaque origin because `allow-same-origin` is absent.

The host delegates the [Fullscreen API](https://fullscreen.spec.whatwg.org/)
for presentation controls. The browser requires a user gesture to enter fullscreen.

The child receives no Studio credential or same-origin authority. A validated
message bridge carries navigation, public query, fragment, readiness, replay,
and diagnostic messages. The wrapper accepts child messages from
the iframe window with origin `null` and parent messages from the same-origin
Studio window.

Presentation responses enforce a sandbox content security policy, a null-origin
CORS audience, no referrer, and explicit exposed headers. Studio documents use
no-store, `nosniff`, and same-origin referrer policy. The native editor bridge
and outer edit documents use one `SecurityPolicy` for `frame-ancestors`. The
policy always includes `'self'` and may include canonical origins loaded from
`MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS` during server composition.
Trusted host scripts carried in Marimo's server-level `html_head` remain in the
outer Studio document. Their bounded `data-parent-origin` declarations extend
the same policy for host-managed embedding without importing host code.

## Session admission

The browser client and native editor session form an explicit binding. A signed
editor capability covers the notebook, base URL, edit mode, server instance,
client, and session. Reconnecting the same pair is idempotent. A conflicting
pair fails before the native transport attaches.

Presentation WebSocket and server-sent event connections receive a
`NativeSessionAdmission`. The session allocator reserves the presentation and
runtime pair before Marimo accepts the transport, then settles or cancels the
claim according to the connection result.

Session replay reuses a Server runtime only when notebook, page path, canonical
public query, and saved creation metadata match. Private routing keys are
removed from the public query comparison.

## Failure and cleanup

- Unknown Studio paths delegate to Marimo or return 404 from an already-owned
  support namespace.
- Unsupported methods return 405 before acquiring mutation owners.
- Missing read or edit authority returns 401 or 403 with a stable error code.
- Invalid presentation capabilities return 403 and WebSockets close with
  policy code 1008.
- Disconnected request bodies return 499. Oversized bodies return 413.
- ASGI shutdown closes notebook scopes, runtimes, native session state, and the
  application-owned adapter group while preserving the first cleanup failure.
  The process-wide presentation-authorization patch closes through `atexit`.

## Contract tests

Protect routing and security with route-level and live tests:

- Prove that Marimo-native paths remain delegated in edit and run modes.
- Exercise every workspace lifecycle state and its repair path.
- Reject presentation capabilities with another view, revision, artifact,
  session, target, method, or server process.
- Verify opaque-origin iframe messaging and blocked same-origin access.
- Reconnect the same editor pair and reject a conflicting pair.
- Verify read, edit, server-token, body-limit, no-store, CORS, and content
  security policy boundaries.
- Close the application while sessions, provider work, and artifact leases are
  active.
