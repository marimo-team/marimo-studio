# View providers and artifacts

Providers adapt frontend source and build tools to Studio's view contract.
Artifacts are Studio-owned immutable browser files.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities. Read [Provider environments](provider-environments.md) for
dependency composition, CLI re-entry, and third-party process ownership.

## Discovery

Providers register under `marimo_studio.view_provider`. The registry derives a
key from the normalized distribution and entry-point name:

```text
acme-views + report -> acme-views/report
```

This makes ownership structural. A third-party distribution cannot claim a
built-in key. Candidate load failures remain visible through `doctor`
and do not hide healthy registrations.

## Provider protocol

```python
class ViewProvider(Protocol):
    info: ProviderInfo

    def availability(self, project=None) -> ProviderAvailability: ...
    def starters(self) -> tuple[ProviderStarter, ...]: ...
    def create(self, starter, context) -> StarterPlan: ...
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

`create()` receives a detached `NotebookSpec` with complete saved cell source
and one `StarterCellTarget` for every ordinary cell. It returns provider-owned
files plus the targets embedded in that source. Package composition selects
`marimo-studio/vanilla:default` when callers omit a starter.

Core validates the plan against the exact observed notebook revision. For
notebook-local configuration, a provisional plan identifies aliases and an
accepted plan renders from the prospective committed notebook. Both plans must
select the same cell targets. Native cell names require no configuration
change. Selected proposed targets become cell aliases in the notebook or
project configuration.

## Inspection

`ProjectInspection` contains:

- ordered `editor_documents` declared safe for the user-facing Source editor
- exact files and bounded recursive directories in `input_scope`
- mount declarations
- diagnostics
- provider build fingerprint

Conformance keeps Studio-owned `view.toml` outside `editor_documents` while it
remains inside `input_scope`. Core watches both sets and enumerates
`input_scope` for revisions and snapshots. Editor documents outside that scope
remain exact provider-authorized source paths without affecting build identity.
Conformance validates path types, control namespaces, document identity,
diagnostic shape, artifact-local projection IDs, and fingerprint presence.

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
    _starters.py  bundled starter records, selection, and resource assembly
    vanilla/      provider and vertical starter packages
    _deno/         shared process, inventory, and analyzer support
    deno_react/   provider, build, analyzer, and vertical starter packages
    deno_svelte/  provider, build, analyzer, and vertical starter packages
```

Framework-specific parsing and diagnostics stay inside the matching
bundled provider. Shared Deno execution, source copying, instrumentation edits,
and public asset handling stay under `_bundled/_deno`.

Each bundled provider composes an immutable catalog in `starters/__init__.py`.
Every `starters/<key>/` package owns one `ProviderStarter`, its renderer, and a
colocated `files/` tree. Adding a starter creates that package and adds one
catalog import. Starter packages never import sibling starters.

Framework declarations and runtime adapters live in each leaf that uses them.
The generic catalog invokes the selected leaf and assembles its `files/` tree
while the provider retains ownership of inspection and build behavior.

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

Input capture retains file identities, directory metadata, and absent declared
paths. The final publication check compares these bounded records, so new input
files also reject a stale candidate. Recursive discovery and content hashing
run before the mutation and publication locks.

Providers never receive artifact receipts, pins, presentations, sessions,
browser clients, or agent requests.

## Publication

Each view has one generated `.artifacts/` store. Development and production
profiles own independent receipts that can point to the same immutable
revision. A publication records compact provider provenance, diagnostics,
duration, project revision, and artifact revision.

Publication uses a fresh staging directory and atomic pointer replacement. A
failed attempt updates build state while retaining the current publication.

One filesystem pin protects each retained revision across processes. Asset
responses share that owner through process-local reference counts. Serving
copies an opened file into a verified snapshot before committing immutable
headers, then streams exactly the recorded byte count.

### Profile state

One profile receipt stores two related records:

- `published` is the last successful publication and its provenance.
- `build` is the latest attempt with phase `unbuilt`, `building`, `failed`,
  `published`, or `stale`.

A failed or interrupted attempt can retain `published`. Presentation and static
export read the retained publication while Source reports the latest attempt.
Damaged generated state resets the affected profile before a new build and
adds an `artifact-state-repaired` diagnostic.

### Retention and integrity

An `ArtifactLease` pins one revision until its browser response, presentation
snapshot, static export, or retained history finishes. Pins use cross-process
file locks. Process-local shares keep the same pin alive until the final share
closes.

Pruning protects revisions referenced by either profile or a live pin. It
removes unowned revisions and retries deletion of quarantined trees whose open
Windows handles delayed cleanup. A damaged revision moves to quarantine before
replacement so opened descriptors can drain before cleanup.

Reads verify manifest membership, recorded byte size, and SHA-256 digest into a
temporary snapshot before any immutable response headers commit. Integrity
failure marks matching profile state stale and requires a rebuild.

### Lock order

Locks have separate ownership scopes:

| Lock                      | Protects                                               |
| ------------------------- | ------------------------------------------------------ |
| Workspace catalog lock    | View membership and catalog-wide configuration         |
| View build lock           | Build or removal ownership for one view name           |
| View mutation lock        | Authored files and final source-identity checks        |
| Artifact lease lock       | New lease admission while a view tree is replaced      |
| Artifact build lock       | Provider work and interrupted-build recovery           |
| Artifact publication lock | Profile receipts, revisions, pins, pruning, and leases |

Catalog mutations acquire the workspace catalog lock before any view lock.
Builds acquire the view build lock, then the artifact build lock. Provider work
runs outside the view mutation lock. Final publication acquires the view
mutation lock for the source stability check, then takes the short artifact
publication lock for revision installation, lease creation, pruning, and
receipt replacement.

Removal acquires the workspace catalog lock, view build lock, and view mutation
lock. When a build owns the view, removal releases the catalog lock before
waiting and revalidates ownership after acquiring the ordered locks. Source
operations on other views remain available during that wait. Its deletion guard
then blocks new leases, checks live pins under the artifact publication lock,
and replaces the project tree. Lease acquisition
takes the lease-admission lock before the artifact publication lock.

Do not wait for provider work, browser I/O, or process cleanup while holding the
artifact publication lock.

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

## Failure behavior

- Provider or validation failure records a failed attempt and retains the
  current publication.
- A changed project revision rejects the candidate before profile commit.
- Cancellation after candidate preparation releases its staging tree and
  lease.
- Missing or damaged receipts are repaired by the owning profile.
- A live cross-process pin rejects view removal with `view-in-use`.
- Revision collision or integrity failure quarantines the suspect physical
  tree before replacement or recovery.

## Validation

Keep local tests for conformance and filesystem safety. Prove extensibility with
one minimal installed provider package and one browser smoke. Prove bundled
providers through source inspection, build failure retention, and live
mount behavior. Add retention cases for both profiles, live pins, history,
quarantine, integrity failure, interrupted builds, pruning, and removal.
