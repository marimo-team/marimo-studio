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

Studio writes the manifest. A starter writes provider-owned source and native
tool files. Starter identity never enters project, artifact, presentation, or
browser identity.

## Creation transaction

`ensure_view()` is idempotent for Python and agent callers. CLI `view create`
fails when the selected name exists.

Creation validates the notebook and starter before writing. Under the workspace
catalog lock, one file transaction writes in this order:

- notebook-local PEP 723 metadata and provider requirements when needed
- the existing workspace `.gitignore` with missing generated-state rules
- `view.toml`
- provider starter files in their declared order

The created view starts in `unbuilt` state. Inspection and build are explicit
operations after the transaction commits.

Providers cannot write core control paths. Creation validates normalized paths,
binary payloads, case collisions, and file-directory overlap before the
transaction starts.

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
