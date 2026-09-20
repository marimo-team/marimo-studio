# Product and workspace

The notebook is the analytical model. A view is one named frontend project
that consumes that model.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities and [Identities and state](identities-and-state.md) for the
generation and revision contract.

## Workspace configuration

Studio reads either PEP 723 notebook metadata or `[tool.marimo-studio]` in
`pyproject.toml`. Configuration selects the notebook, default view, permitted
runtimes, log behavior, session preservation, and optional cell aliases.

Notebook-local views live at:

```text
__marimo__/studio/<notebook-stem>/<view-name>/
```

Configuration can select a portable relative `view_root` when the embedding
host reserves `__marimo__/` for generated runtime state. Every catalog,
mutation, build, and publication operation then uses that resolved root.

The workspace writes one `.gitignore` for `.locks/` and every view's
`.artifacts/`.

## Workspace lifecycle

The server resolves one saved notebook into an explicit lifecycle state:

```text
unconfigured
  -> configured and needs first view
  -> ready
```

Configuration or project failures enter `invalid` from any discovery step. The
edit application keeps a repair surface available for incomplete states. Run
mode requires a ready workspace before it serves a named view.

An unconfigured notebook exposes the first-view application at `/studio/`.
The default edit root keeps the native editor host available until Studio is
configured. The create request plans the starter against the saved notebook,
commits the complete view project, writes configuration, then reloads Studio
from the resulting ready workspace. A configuration that already names a
default view but has no discoverable `view.toml` enters `needs-view` and uses
the same create path.

The Studio host treats a bootstrap response as a snapshot. If another client
creates the first view before the request commits, the host refreshes lifecycle
state and opens the existing ready workspace.

## First save

An untitled Marimo editor begins with a temporary `__new__*` file key and one
native session. After `/api/kernel/save` succeeds, the editor bridge resolves
the saved notebook from that exact session and asks Marimo to reload Studio
integration for the new path.

The handoff reuses the native session after the saved notebook, session owner,
and public query still match. A file-key change preserves that session owner.
The browser stays on the native editor until a first view is created, then
transitions into the Studio route with the same session binding.

## View manifest

```toml
schema = 1
provider = "marimo-studio/vanilla"

[options]
entrypoint = "web/report.html"
```

`provider` uses `distribution/entry-point` form. `options` stores explicit
overrides. The selected provider validates that mapping and applies its defaults
inside its inspection and build operations.

Studio stores per-name incarnation records in
`__marimo__/studio/<notebook-stem>/.owners/`. Each record contains a 64-character
generation and whether the name is present. View generation combines that
durable owner with the current project-directory owner. Create and delete update
the owner record in the same file transaction as configuration. Catalog loading
adopts external names and records names observed as absent through the catalog
lock.

The 0.1 mutation owner covers Studio create and delete, external absences seen
by catalog loading, and copies or renames with a distinct directory owner. An
external delete and recreation that occurs between observations and reuses the
same device, inode, and mode has no observable directory identity change. That
case is outside the mutation-ownership contract and includes exact-byte
recreation.

Studio writes the manifest. A starter writes provider-owned source and native
tool files. Starter identity never enters project, artifact, presentation, or
browser identity.

## Creation transaction

`Workspace.create_view()` and CLI `view create` reject an existing view name.
Call `Workspace.view(name)` to operate an existing project.

Creation validates the notebook and starter before writing. Under the workspace
catalog lock, one file transaction claims and pins each new view directory,
writes its provider files, and keeps the project undiscoverable until
`view.toml` publishes the complete project. The same transaction writes the
fresh per-name owner and any missing generated-state rules in the workspace
`.gitignore`.

The first view is complete before notebook-local PEP 723 metadata declares the
workspace. Existing workspaces receive required configuration before the new
`view.toml` becomes discoverable. Readers therefore observe the prior workspace
or the complete new catalog.

The transaction carries the file identities read during planning and expected
absence for new paths. Conditional replacement rejects concurrent notebook,
configuration, or project-file changes before the catalog commits. A failed
condition restores files already written by the transaction and preserves the
concurrent edit.

Each new view directory is claimed while absent and held through a stable
directory owner. Every child write uses that owner. The root incarnation and
complete file catalog are verified before and after workspace materialization,
so creation cannot adopt a replacement directory or unknown files from a
competing writer.

The created view starts in `unbuilt` state. Inspection and build are explicit
operations after the transaction commits.

Providers cannot write core control paths or cell bindings. Creation validates
normalized paths, binary payloads, selected starter targets, case collisions,
and file-directory overlap before the transaction starts.

## Source catalog and documents

`_views` owns source document access and mutation policy. `_workspace` owns the
manifest and transaction primitives used by that policy.

Provider inspection returns ordered documents with `edit` or `read` access.
The browser Source catalog contains those provider documents and keeps
`view.toml` outside the catalog. The saved-workspace `View.inspect()` API
prepends Studio's editable `view.toml` record to its result. When provider
loading or inspection fails, the lifecycle support route still exposes
`view.toml` directly. Manifest reads and writes use provider-free workspace and
view owner records.

Editing `view.toml` can change explicit provider options. It cannot change the
provider key for an existing view. Create another view to select another
provider.

Every source read returns UTF-8 content and a document revision. CLI JSON reads
also return catalog and view generations. Browser Source reads pair the document
revision with owner generations from the project payload. Source writes hold
the catalog and view mutation locks, revalidate document access and owner
generations, compare `If-Match`, preserve the file mode, and replace through a
same-directory temporary file. Provider documents also retain the inspected
input state so a concurrent authorization or build-input change rejects the
save and restores the previous bytes.

The browser owns unsaved recovery content. A losing writer receives the current
revision and keeps its buffer.

## Notebook mutation admission

The native editor asks each active Preview owner to pause before a notebook
document transaction commits. The Preview sends a revision-bound refresh
barrier to its presentation document, waits for an acknowledgement, then admits
the editor mutation generation.

One mutation settles after the editor reports that the transaction applied and
the matching presentation build completes. An unchanged transaction can settle
through the barrier owner. A failed save or transaction keeps Preview fenced
and reports a runtime diagnostic until a later authoritative save and build
reconcile it.

A newer save can subsume earlier completion messages. Reloading the native
editor starts a fresh mutation-generation namespace, clears pending owners,
marks cached views stale, and resets active Preview admission.

## Development state

`DevelopmentCoordinator` shares one source monitor per view across browser
clients. `PublicationRegistry` coalesces publication work by `(view, source
generation, build profile)` while that work is in flight. Together they own:

- current project inspection
- source generation
- source journal
- in-flight publications
- latest build state per profile
- subscribers
- deletion coordination

New source generations cancel obsolete publication owners. Development and
production retain independent latest build state. Browser clients retain
separate source buffers and cursor state.

## View removal

Removal requires at least one remaining view. It stages the view directory,
updates the default when needed, validates the remaining workspace, then removes
the staged directory. Python dependencies remain unchanged.

Artifact pins block removal while another process owns a published revision.

Server removal validates the observed catalog and view before draining local
development work. The catalog stays available during that drain and while a
build owns the view. Removal then acquires the ordered filesystem locks and
revalidates both generations before releasing presentation artifacts. A changed
owner rolls development back and preserves the presentation.

Presentation coordination precedes the filesystem locks, matching snapshot
capture. Its artifact release is staged until the final owner check succeeds.

## Notebook symbols

`NotebookSymbolGraph` maps named cells and variables to stable semantic
producers and dependency closures. Native Marimo cell names are the preferred
view-facing target. `CellRef` aliases support existing anonymous cells.

Resolution is scoped to the selected view and current saved notebook. Runtime
authorization revalidates the live dependency closure before dispatch.

## Tests

Protect these contracts:

- one-file starter creation
- conflicting ETag writes from two clients
- provider-independent `view.toml` repair
- first save preserving the native editor session
- notebook mutation pause, save, build, failure, and reload ordering
- failed build retaining the last publication
- same provider and explicit options producing one input identity
- deletion preserving the remaining default
- literal and bounded notebook target resolution
