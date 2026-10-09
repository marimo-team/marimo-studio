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

    def availability(self) -> ProviderAvailability: ...
    def starters(self) -> tuple[ProviderStarter, ...]: ...
    def create(self, starter, context) -> StarterPlan: ...
    def inspect(self, request) -> ProjectInspection: ...
    def build(self, request) -> BuildResult: ...
    # optional, for rendered documents
    def render(self, request) -> BuildResult: ...
```

Provider methods are synchronous. Built-in providers run in process. Server
owners move their synchronous calls off the event loop, and built-in providers
can observe `request.cancellation`. They should return promptly when it is
cancelled. Both paths run the provider through the same conformance adapters,
so a `ProviderError` becomes the same diagnostic in process and in the worker.

Installed third-party operations run in owned subprocesses. Host cancellation
terminates the operation process tree. The isolated worker creates a local
`ProviderCancellation`, but host cancellation does not signal that object
before termination. Provider Python in the worker must not rely on cooperative
cancellation or `finally` blocks for cancellation cleanup.

`ProviderRunner` enforces output bounds and one finite aggregate command budget.
The owning supervisor covers descendant cleanup, and each command timeout is
validated and clamped to the budget's remaining time.

`ProviderInfo` contains title, summary, and the provider options the provider
reads. Conformance rejects any other option with
`provider-options-invalid` before it calls the provider, and the remaining
options reach the provider as a detached JSON-compatible mapping. The provider
validates their values, usually through `ViewProject.path_option()`. A
`ProviderError` from `inspect()`, `build()`, or `render()` becomes an error
diagnostic. Any other exception is a provider failure. Final registry
diagnostics contain the safe key when available, distribution, version,
availability, accepted starters, and load or runtime errors.

## Starters

A starter is creation-time data. Its starter key, title, summary, and Source
documents are shown to people and agents. Public catalogs name a starter by
its starter ID, `<provider key>:<starter key>`, so independent providers can
use the same starter key.

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

- ordered Source documents in `documents`
- build inputs in `inputs`: exact files and bounded recursive directories
- projection sites, each with a source location and a UTF-8 byte offset inside
  the host start tag
- diagnostics
- render values read by a rendered document

Conformance adds Studio-owned `view.toml` to the build inputs, and adds
`AGENTS.md` and `DESIGN.md` to the Source documents when they exist. Core
watches both sets and enumerates the build inputs for revisions and snapshots.
Source documents outside the build inputs remain exact provider-authorized
source paths without affecting build identity. Conformance validates path types,
control namespaces, document identity, diagnostic shape, and site placement
inside build inputs. A render value whose target is invalid becomes a
`render-value-invalid` diagnostic at its source.

Core derives an `ArtifactSite` from each projection site in
`_artifact_sites.py`. A site ID
hashes the path, kind, single target, and occurrence of that key in offset
order, so unrelated layout edits keep existing IDs. Providers never see site
IDs.

Provider provenance hashes the distribution, its version, the provider key,
Studio's build contract version, and the tool version from `availability()`.
These feed the project revision, so a provider release or tool upgrade makes the
published artifact stale and the view builds again.

## Provider layout

The public SDK, private host, and built-in implementations live under one
provider package:

```text
view_providers/
  __init__.py      public SDK: records, protocols, and helpers
  _records.py      provider records and protocols
  _toolkit.py      project_files, copy_inputs, project_path, probe_tool
  _starters.py     PackagedStarter, create_starter, script_json
  _sites.py        html_sites
  testing.py       check_provider, the public conformance kit
  _host/           discovery, conformance, starters, and isolated operations
  _builtin/
    vanilla/          provider and vertical starter packages
    _deno/            shared Deno process, inventory, and analyzer support
    deno_react/       provider, build, analyzer, and vertical starter packages
    deno_svelte/      provider, source check, analyzer, and vertical starter packages
    deno_obsnotebook/ provider, notebook HTML analyzer, and vertical starter packages
    quarto/           provider, Markdown site scanner, marimo shortcode extension, Lua filter, and starter
    _typeset.py       shared inspection and media placement for typeset documents
    typst/            provider, value scanner, compile script, and starter
    latex/            provider, command scanner, render inputs, Tectonic compile, and starter
```

The SDK re-exports the operation types from `_processes/operation.py`, so a
provider imports every name from `marimo_studio.view_providers`. The same
package also holds core modules that providers never import: `_document.py`,
`_javascript.py`, and `_css_resources.py` analyze HTML, JavaScript, and CSS for
vanilla and delivery preflight, `_validation.py` checks provider records, and
`_artifact_sites.py` and `_targets.py` turn projection sites into artifact
sites.

### Built-in providers use the public SDK

Each built-in provider is written as if it were already its own distribution:

- It imports Studio only through names in `marimo_studio.view_providers`.
- It imports other built-in code only from its own subpackage and from a
  declared shared library. `_deno` is the shared library for the `deno_*`
  providers, and `_typeset` for the Typst and LaTeX providers.
- Vanilla is the core built-in. It may also import `_filesystem`, `errors`,
  and the HTML, JavaScript, and CSS analyzers in `view_providers`.

`scripts/check_python_architecture.py` enforces these rules, and
`tests/providers/test_builtin_contract.py` runs every built-in provider through
`check_provider()`. A provider that needs a capability the SDK lacks gets a
public helper first. Add a helper when two providers need it, or when it hides
a Studio rule such as path normalization, input limits, or cancellation.

Moving a provider to its own distribution changes its key, because the key
embeds the distribution name. Its `view.toml` files then need the new key, and
`BUILTIN_PROVIDER_REQUIREMENTS` stops listing it.

### Add a built-in provider

1. Create `_builtin/<name>/` with `__init__.py` exporting `provider`, and a
   `starters/` catalog of `PackagedStarter` records.
2. Register the entry point in `packages/marimo-studio/pyproject.toml` and add
   its requirement to `BUILTIN_PROVIDER_REQUIREMENTS` in
   `_host/package_policy.py`.
3. When it needs an external tool, add the tool's pytest marker to `_PROFILES`
   in `tests/providers/test_builtin_contract.py`.
4. Document its starters and options in `docs/reference/built-in-providers.md`
   and add it to the layout above.
5. Run `scripts/check_python_architecture.py` and the built-in contract test.

Framework-specific parsing and diagnostics stay inside the matching
built-in provider. Shared Deno execution, analyzer runs, and public asset
handling stay under `_builtin/_deno`. Svelte and Notebook Kit share the
contained Vite build pipeline. Svelte supplies its source check before the
build. Notebook Kit's Vite plugin transforms the instrumented notebook, so site
attributes survive reactive replacement of HTML cells.

Each built-in provider composes an immutable `STARTERS` tuple of
`PackagedStarter` records in `starters/__init__.py`. Every `starters/<key>/`
package owns one `ProviderStarter`, its `StarterMarkers` function, and a
colocated `files/` tree. Adding a starter creates that package and adds one catalog import.
Starter packages never import sibling starters. `create_starter()` assembles
the selected `files/` tree while the provider retains ownership of inspection
and build behavior.

## Build lifecycle

Studio discovers inputs from the live project, copies them into a private
snapshot, and treats the snapshot inspection as the build authority. Core
inserts `data-marimo-studio-site` at each site offset in the snapshot through
`_views/instrumentation.py`, then calls `build()`. The provider writes a
candidate beneath its supplied staging root. Core shifts diagnostic columns on
instrumented lines back to authored source. Studio copies the candidate's
regular files into a new directory that only Studio writes, then validates,
hashes, and publishes that copy, and warns with `projection-site-missing` when
a site ID is absent from it.

Core validates:

- path containment and normalized public paths
- symlinks and special files in provider output
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

## Document views

A provider with `render()` publishes rendered documents, and its build document
is a template entry of any type. For other providers, an `.html` build document
is a live page, and a PDF, SVG, or PNG publishes behind a generated viewer
page.

`_views/documents.py` composes document views, and its `render_document()`
renders a fresh template copy for builds, live renders, and static exports. For
a document, `compose_view()` ingests the staging tree into a directory only
Studio writes. A template becomes the revision's private `template/` directory,
and Studio renders it once with empty values to validate it and publish the
first document, and writes a viewer `index.html` whose `<marimo-document>`
holds one hidden `mo-value` host per value target, one hidden
`marimo-output` host per output target, and one hidden `marimo-cell` host per
cell target. The manifest records the template files
and the renderer fingerprint, and both belong to the artifact revision
identity. Asset routes and static exports read the public file catalog, so
template files stay private.

`render_sites()` gives each document value site the accept list
`("application/json",)`, so every runtime reads that value through
marimo-export's `represent()` as JSON: a table becomes row objects and a date
ISO 8601 text, where a browser view's value site reads a table as Arrow. A
build that compiles its template returns `BuildResult.output_sizes`, the size
the template places each output at, and `_views/build.py` passes it to
`render_sites()`, which records it on the output site. The size travels with the accept list through the signed
projection records to the kernel, the Pyodide bridge, and the prepared export's
`media` exporter, which all draw the figure at that size. Both belong to the
artifact revision identity, because a site's `to_dict()` holds them.

`_server/presentation/document_renders.py::DocumentRenders` owns live render
workers and cached renditions on `NotebookScope`, and
`_server/presentation/documents.py` serves the render route. The Python runtime reads render values and outputs through
`read_kernel_values()` and `read_kernel_outputs()`, the same authorized reads
as the value and output routes, and cell outputs from the marimo session
through `read_session_cells()`. Edit mode also accepts the values, outputs, and
cell outputs that a browser runtime's hosts show, as `marimoValue` and
`marimoOutput`. `_projections/runtime_records.py::output_representation()`
turns each marimo output into bytes by media type for the provider. For a cell
it picks the first accepted type in marimo's mimebundle. An output it cannot
decode leaves the template's default. Each render belongs to its HTTP request: a
client disconnect cancels the provider commands and waits for them to stop
before the route returns. Renders run on two owned worker threads in a fresh
copy of the template, with a 60 second command budget. A template copy that
fails integrity verification marks the publication stale, so the next build
repairs it. A 64 MiB LRU cache keyed by artifact revision and the digest of
canonical values, output bytes, and cell bytes serves repeated renders. A
worker stores each rendition before it takes the next request, so identical
requests queued behind it reuse the rendition. Closing the scope
cancels active renders, waits for the workers, and drops the cache.

The `<marimo-document>` viewer keeps one render request in flight. Values that
change meanwhile queue one more render after it settles, so the document
catches up with the latest values.

Zero-python static export renders the template once per prepared state into
`renditions/<state fingerprint><ext>` through `_delivery/documents.py`, from
each state's exported values, outputs, and cell snapshots. The browser viewer selects the
rendition for the current state. WASM static export publishes the build-time
document, which the viewer shows with a note that current values are
unavailable.

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
A build discards profile state that it cannot read and publishes again.
Readers treat state written by another Studio version as unbuilt until that
build runs. The build logs the repair, as described in
[Automatic recovery and logs](errors-and-diagnostics.md#automatic-recovery-and-logs).

### Retention and integrity

An `ArtifactLease` pins one revision until its browser response, presentation
snapshot, static export, or retained history finishes. Pins use cross-process
file locks. Process-local shares keep the same pin alive until the final share
closes.

Presentation history retains up to eight snapshots per profile, all from that
profile's current and previous build, so a running server keeps at most those
revisions plus the ones in-flight responses and exports still read.

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

`_filesystem.files.FileTree` owns every file change under one root. On POSIX
systems, each verb opens the root and walks to the target's parent through
directory descriptors opened with `O_NOFOLLOW`, then acts on the leaf relative
to that descriptor. A swapped ancestor either fails the walk or leaves the
operation in the directory it resolved. A tree binds to the root directory its
first verb opens, so a multi-step operation refuses to continue once the root
path names another directory. Windows offers no descriptor-relative file API, so
each verb checks the path for symlinks and junctions before it acts. Data reparse
points such as cloud files are reopened through the filesystem filter, while a
junction that replaces a checked ancestor between that check and the operation
is not refused.

| Verb                    | Primitive                                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `read`                  | Bounded read that returns content with an opaque `Version`                                                              |
| `write`                 | Same-directory temporary file, `fsync`, then replace                                                                    |
| `write(expect=ABSENT)`  | Publish the new file while its name stays absent                                                                        |
| `write(expect=version)` | Move the current file aside, compare its `Version`, publish or restore                                                  |
| `remove(expect=...)`    | Move the entry aside, compare its `Version` or `TreeVersion`, delete or restore                                         |
| `publish`               | Move an entry onto a name that must stay absent                                                                         |
| `lock`                  | `flock` or `msvcrt` byte-range lock on a persistent lock file                                                           |
| `ingest`                | Copy provider output into a new directory, through directory descriptors on POSIX and held directory handles on Windows |

`publish` uses `renameat2(RENAME_NOREPLACE)` on Linux and
`renameatx_np(RENAME_EXCL)` on macOS. NFS, WSL drive mounts, and gVisor host
mounts reject that flag with `EINVAL`. There, a file publishes through an
exclusive hard link and a directory through an empty placeholder that the rename
replaces. On Windows, `MoveFileExW` renames whichever entry its source handle
opened, so concurrent renames of one path can all succeed. Studio renames
through a handle that withholds delete sharing. A competing rename of the same
entry gets a sharing violation, which Studio retries for about one second before
it reports the entry as busy.

Provider builds are the lower-privilege writers, because a Deno build may write
only beneath its staging root. `ingest` copies their regular files into a
directory that only Studio writes and rejects symlinks and special files, so
publication and serving never read a tree that a build can still change.

The threat model covers concurrent path replacement by local processes. A
process that can modify Studio's memory, descriptors, or executable code is
outside it.

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
one minimal installed provider package, `scripts/verify-external-provider.py`,
and one browser smoke. Prove built-in providers through `check_provider()`,
source inspection, build failure retention, and live projection behavior. Add
retention cases for both profiles, live pins, history, quarantine, integrity
failure, interrupted builds, pruning, and removal.
