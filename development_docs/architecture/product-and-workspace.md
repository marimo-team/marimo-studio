# Product and workspace

The notebook is the analytical model. A view is one named frontend project
that consumes that model.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Workspace configuration

Studio reads either PEP 723 notebook metadata or `[tool.marimo-studio]` in
`pyproject.toml`. Configuration selects the notebook, default view, permitted
runtimes, log behavior, session preservation, and optional cell aliases.

Notebook-local views live at:

```text
__marimo__/studio/<notebook-stem>/<view-name>/
```

The workspace writes one `.gitignore` for `.locks/` and every view's
`.artifacts/`.

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

## Source documents

`_views` owns source document access and mutation policy. `_workspace` owns the
manifest and transaction primitives used by that policy.

Provider inspection returns ordered documents with `edit` or `read` access.
Source reads use the shared development catalog and one file ETag. Source writes
hold the view mutation lock, revalidate document access, compare `If-Match`,
preserve the file mode, and replace through a same-directory temporary file.

The browser owns unsaved recovery content. A losing writer receives the current
revision and keeps its buffer.

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
- failed build retaining the last publication
- same provider and explicit options producing one input identity
- deletion preserving the remaining default
- literal and bounded notebook target resolution
