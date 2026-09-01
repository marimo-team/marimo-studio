# Errors and diagnostics

Expected Studio failures use one stable code and recovery shape across Python,
CLI, HTTP, validation, Source, Preview, and agent surfaces.

See [Identities and state](identities-and-state.md) for stale-state failures
and [Server routing and security](server-routing-and-security.md) for HTTP
authorization failures.

## Decision

`MarimoStudioError` is the domain boundary for expected failures. Every subtype
can define:

| Field                  | Meaning                                                          |
| ---------------------- | ---------------------------------------------------------------- |
| `code`                 | Stable machine-readable failure identity                         |
| Exception text         | Contributor and CLI diagnostic detail                            |
| `public_message()`     | Browser-safe message when path or internal detail must be hidden |
| `exit_code`            | CLI process result                                               |
| `status_code`          | HTTP response status                                             |
| `transient`            | Whether the same operation may succeed after state settles       |
| `public_hint`          | Concrete recovery action                                         |
| `diagnostic_details()` | Structured path, revision, owner, choice, or recovery data       |

Use a subtype when the operation has stable recovery semantics. Use
`CapabilityInputError` when one agent or browser request field is invalid. Use
`AgentRequestError` when the server has already supplied a stable remote code,
status, details, hint, and transient classification.

Unexpected exceptions remain programming, platform, or cleanup failures. Do
not convert them to a generic success or a domain code that implies a known
recovery path.

## CLI translation

Human output writes one error and an optional `Hint:` to stderr. `--json`
writes command results to stdout and schema 1 diagnostic events to stderr.

| Exit code | Owner                                           |
| --------: | ----------------------------------------------- |
|         0 | Successful operation                            |
|         1 | Validation or provider availability failure     |
|         2 | CLI usage or invalid capability input           |
|         3 | General expected Studio failure                 |
|         4 | Notebook binding failure                        |
|         5 | Agent or live browser request failure           |
|         6 | Protocol or pinned-Marimo compatibility failure |
|         7 | Dependency or environment preparation failure   |
|       130 | User interruption                               |

A JSON Lines diagnostic contains `schema`, `event`, `command`, `severity`,
`code`, and `message`. It adds `exit_code`, `status`, and `details` when the
owning error supplies them. The re-entry protocol accepts trusted events from
its private diagnostic channel and turns unmatched process output into a
bounded warning.

## HTTP translation

Structured responses use:

```json
{
  "error": "source-conflict",
  "message": "index.html changed on disk.",
  "revision": "sha256:..."
}
```

`error_response()` preserves the domain status and adds no-store headers. Page
responses also expose `Marimo-Studio-Error`, optional `Marimo-Studio-Hint`, and
transient retry headers. Browser-safe messages remove repository root paths.

Support and agent routes use JSON. Presentation documents can receive a repair
page in edit mode and plain configuration text in run mode. Presentation
capability failures use narrow route-owned codes because they occur before a
domain handler accepts the request.

Request parsing owns these failures:

- 400 for malformed JSON or an invalid field
- 401 for missing authentication or mismatched process authority
- 403 for missing edit access or rejected capability authority
- 404 for a missing view, document, artifact, or provider
- 409 for stale identity, pending synchronization, or in-use state
- 412 for a Source revision conflict
- 413 for an exceeded body, document, runtime configuration, or value limit
- 499 for a disconnected caller
- 503 for bounded capacity or a closing owner
- 504 for runtime or agent timeout

## Provider diagnostics

`ProjectDiagnostic` carries code, `warning` or `error` severity, message, hint,
and optional project-relative source location. Providers create diagnostics for
their own source and build semantics. Core validates paths, shape, source
membership, and bounded counts before exposing them.

Core adds diagnostics for artifact validation, publication, recovery, stale
inputs, and cancellation. A failed build stores its diagnostics in the latest
attempt while retaining the current published artifact.

Source places provider and build diagnostics on the owning document when a
location is present. Project-wide diagnostics remain visible at the view level.

## Projection and browser diagnostics

Projection resolution converts provider mount declarations and notebook graph
failures into diagnostics with view, projection kind, target, source location,
and optional declaration ID.

Browser diagnostics add runtime scope and current presentation identity.
`RuntimeStatusReport` retains an increasing, bounded transition history with
one current phase:

- `connecting`
- `synchronizing`
- `ready`
- `degraded`
- `failed`

`ready` carries no diagnostics. `degraded` and `failed` carry at least one.
The latest transition must match the current snapshot. A browser observation
must carry the same runtime, view, presentation revision, session, and current
diagnostics as its runtime status report.

## Validation issues

Validation converts failures into `CheckResult` records. A result owns stage,
status, stable code, message, and optional source, view, projection, producer,
dependency closure, declaration, and hint details.

Static, runtime, and browser validation remain cumulative. A later stage may
add evidence but cannot rewrite an earlier failure into another code. Source
revisions are checked before and after contained runtime work so evidence from
moving source is rejected.

## Translation rule

Translate a failure once at the boundary that changes its audience:

```text
provider or adapter failure
  -> Studio domain error or diagnostic
  -> CLI, HTTP, validation, or browser record
  -> human rendering
```

Preserve the stable code, source owner, transient classification, and recovery
action. Add context such as view, target, or current revision. Do not replace a
specific upstream code with a generic wrapper.

## Contract tests

- Assert one domain error through human CLI, JSON Lines CLI, structured HTTP,
  and agent translation.
- Keep status, exit code, transient flag, hint, and structured details aligned.
- Sanitize browser messages while retaining source paths relative to the
  notebook or view project.
- Reject provider diagnostics that name undeclared documents.
- Retain a published artifact while surfacing a later build failure.
- Reject browser observations whose identity or runtime status disagrees.
- Bound extension output, diagnostic counts, messages, and histories.
