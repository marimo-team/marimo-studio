# View providers and artifacts

Providers adapt frontend source and build tools to Studio's view contract.
Artifacts are Studio-owned immutable browser files.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Discovery

Providers register under `marimo_studio.view_provider`. The registry derives a
key from the normalized distribution and entry-point name:

```text
acme-views + report -> acme-views/report
```

This makes ownership structural. A third-party distribution cannot claim a
built-in key. Candidate load failures remain visible through `provider doctor`
and do not hide healthy registrations.

## Provider protocol

```python
class ViewProvider(Protocol):
    info: ProviderInfo

    def availability(self, project=None) -> ProviderAvailability: ...
    def starters(self) -> tuple[ProviderStarter, ...]: ...
    def create(self, starter, context) -> Mapping[PurePosixPath, bytes]: ...
    def inspect(self, request) -> ProjectInspection: ...
    def build(self, request) -> BuildResult: ...
```

Provider methods are synchronous. Bundled providers run in process. Server
owners move their synchronous calls off the event loop, and bundled providers
can observe `request.cancellation`. They should return promptly when it is
cancelled.

Installed third-party operations run in owned subprocesses. Host cancellation
terminates the operation process tree. The isolated worker creates a local
`ProviderCancellation`, but host cancellation does not signal that object
before termination. Provider Python in the worker must not rely on cooperative
cancellation or `finally` blocks for cancellation cleanup.

`ProviderRunner` enforces output bounds and one finite aggregate command budget.
The owning supervisor covers descendant cleanup, and each command timeout is
validated and clamped to the budget's remaining time.

`ProviderInfo` contains title, summary, and API version. Explicit `view.toml`
options reach the provider as a detached JSON-compatible mapping. Provider
inspection reports unsupported keys and values. Final registry diagnostics
contain the safe key when available, distribution, version, availability,
accepted starters, and load or runtime errors.

## Starters

A starter is creation-time data. Its provider-local key, title, summary, and
document plan are shown to people and agents. Studio qualifies the local key
as `provider:key` in its public catalogs. Independent providers can use the
same local key.

`create()` returns provider-owned files. Studio writes `view.toml`. Package
composition selects `marimo-studio/vanilla:default` when callers omit a
starter.

## Inspection

`ProjectInspection` contains:

- ordered `editor_documents` declared safe for the user-facing Source editor
- exact files and bounded recursive directories in `input_scope`
- mount declarations
- diagnostics
- provider build fingerprint

Conformance keeps Studio-owned `view.toml` outside `editor_documents` while it
remains inside `input_scope`. Core enumerates that scope for revisions,
snapshots, and watching. It validates path types, control namespaces, editor
document membership, diagnostic shape, artifact-local projection IDs, and
fingerprint presence.

The build fingerprint captures provider-owned semantics. Core combines it with
distribution, version, provider key, and API version.

## Provider layout

The public contract, private host, and bundled implementations live under one
provider package:

```text
view_providers/
  __init__.py      public provider API
  _host/           discovery, conformance, and isolated operations
  _bundled/
    vanilla/        provider, template
    _deno/         shared process, inventory, and analyzer support
    deno_react/    provider, build, analyzer, template
    deno_svelte/   provider, build, analyzer, template
```

Framework-specific parsing and diagnostics stay inside the matching
bundled provider. Shared Deno execution, source copying, instrumentation edits,
and public asset handling stay under `_bundled/_deno`.

## Build lifecycle

Studio discovers inputs from the live project, copies them into a private
snapshot, and treats the snapshot inspection as the build authority. The
provider writes a candidate beneath its supplied staging root.

Core validates:

- path containment and normalized public paths
- symlinks and hard-link detachment
- input and output size budgets
- reserved routes
- the entry document and complete file catalog
- live input stability before publication

Providers never receive artifact receipts, pins, presentations, sessions,
browser clients, or agent requests.

## Publication

Each view has one generated `.artifacts/` store. Development and production
profiles point to immutable revisions. A publication records compact provider
provenance, diagnostics, duration, input revision, and artifact revision.

Publication uses a fresh staging directory and atomic pointer replacement. A
failed attempt updates build state while retaining the current publication.

One filesystem pin protects each retained revision across processes. Asset
responses share that owner through process-local reference counts. Serving
copies an opened file into a verified snapshot before committing immutable
headers, then streams exactly the recorded byte count.

## Filesystem threat model

Studio protects authored source, manifests, build snapshots, publication
receipts, pins, and rollback data from concurrent path replacement inside the
workspace. A competing local process may replace a path with a symlink, a
Windows reparse point, another file, or another directory between validation
and mutation.

On POSIX systems, `_filesystem/secure.py` holds parent descriptors and uses
descriptor-relative operations with no-follow flags. On Windows, it holds
native directory handles and rejects reparse points before leaf access. Atomic
writes use same-directory temporary files and identity-checked rollback.

The boundary supports Linux, macOS, and Windows filesystems with the required
descriptor or native-handle primitives. It does not defend against a process
that can modify Studio's memory, descriptors, or executable code. The custom
code is limited to stable-parent access, regular-file identity, atomic replace,
and rollback recovery because Python's portable file APIs do not provide that
combined contract.

## Validation

Keep local tests for conformance and filesystem safety. Prove extensibility with
one minimal installed provider package and one browser smoke. Prove bundled
providers through source inspection, build failure retention, and live
mount behavior.
