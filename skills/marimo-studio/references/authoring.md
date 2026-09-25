# Authoring and source recovery

Examples assume `workspace` and `view` were acquired for the intended notebook
and view in the current call. Reacquire both in each code-mode execution.

Edit source with Studio's guarded writes or the environment's filesystem
tools. Use `inspection.root` as the project root. Studio writes require a
catalog document with `access="edit"`. Provider inspection owns source discovery
and build inputs for either editing path. Keep generated `.artifacts/` files
under Studio's ownership. Use view files for structure, wording, styles, and
browser interaction.

The view project owns page layout, styles, icons, and browser dependencies.
Mount the authored page or component beneath `#app-shell`.

Use the design source chosen in the core workflow. Keep components, functions,
and modules focused on one responsibility, with domain names and explicit data
and interaction dependencies. Prefer declarative markup and derived values.
Use the project's formatter and review its diff before building. When no
formatter is declared, preserve the existing conventions.

## Add files when the starter needs more structure

A Vanilla view can keep its HTML entry document self-contained or reference
project-local CSS and JavaScript directly. Reference `.css` through
`<link rel="stylesheet">` and `.js` or `.mjs` JavaScript through
`<script src>`:

```html
<link rel="stylesheet" href="./styles/app.css" />
<script type="module" src="./scripts/app.mjs"></script>
```

The Vanilla provider resolves each path relative to the entry HTML.
`view.inspect()` exposes each exact referenced file as one of the provider's
editable source documents and adds it to the build inputs. The build copies
those files to the same paths in the browser artifact.

Follow the HTML project's `AGENTS.md` for local dependency boundaries, accepted
JavaScript grammar, and external assets. Choose a provider that builds a module
graph when the project needs one.

React and Svelte view projects can grow beyond the starter files. Put focused
components, hooks, actions, utilities, and styles beneath `src/`, then import
them from the existing application source. Provider inspection discovers
supported text files beneath `src/` recursively. The next inspection exposes
each discovered file as a source document, and the provider's existing build
input scope includes it. Create UTF-8 text with a provider-supported extension
and keep the path inside the view project.

`view.toml` stores the provider and provider options. Provider inspection owns
source discovery. A new component or utility needs an import from the
application, while the manifest remains unchanged. Unknown manifest fields are
rejected.

`view.write()` and `marimo-studio view write` conditionally replace documents
already returned by `view.inspect()`. For CLI edits, read with `--json` and pass
its `revision`, `catalog_generation`, and `view_generation` through the required
write flags. Locate the exact project root before creating another
provider-supported file:

```python
inspection = await view.inspect()
print(inspection.root)
```

Create the path with a create-if-absent filesystem operation. Studio's
guarded document writes become available after `view.inspect()` returns the
new file. For a React view, a clean factoring pass might create
`inspection.root / "src/lib/format-value.ts"`, import it from `src/App.tsx`, and
then inspect the project again:

```python
inspection = await view.inspect()
created = next(
    document
    for document in inspection.documents
    if document.path.as_posix() == "src/lib/format-value.ts"
)
assert created.access == "edit"
```

Confirm that inspection includes the new file in the intended source or build
inputs. Continue editing through filesystem tools or `view.read()` and guarded
`view.write()`, then build and validate the view.

Edit `view.toml` only when an option supported by the selected provider
genuinely changes. For example, after moving a Vanilla view's HTML entry
document to `pages/index.html`, parse and serialize TOML, preserve the selected
provider, and save through the same revision-aware API:

```python
import tomlkit

manifest = await view.read("view.toml")
config = tomlkit.parse(manifest.content)
options = config.get("options")
if options is None:
    options = tomlkit.table()
    config["options"] = options
options["entrypoint"] = "pages/index.html"

await view.write(
    "view.toml",
    tomlkit.dumps(config),
    expected_revision=manifest.revision,
)
```

## Save against the version you read

Read each affected file immediately before writing it. For a Vanilla view:

```python
document = await view.read("index.html")
updated = document.content.replace("Current heading", "Quarterly revenue")

await view.write(
    "index.html",
    updated,
    expected_revision=document.revision,
)
```

`SourceConflictError` means a person or another agent saved first. Read the file
again, incorporate both changes, and save against the current revision.

## Coordinate filesystem edits and recover

`view.inspect()` reads current disk content. Build and validation also inspect
current source. After external edits, inspect again and read the diagnostics,
`files_complete`, `project_revision`, `published_project_revision`, and
`latest_build`. `build` is the retained successful artifact. Compare the
browser document's committed revision with the revision you intend to inspect.

Compare complete inventories with `after.changes_since(before)` for added,
modified, and deleted source and build-input paths. Incomplete provider or
manifest discovery requires repair and a fresh inspection before comparison.
`view.toml` remains readable and writable through its manifest path.

For edits that pass through valid intermediate states, hold publication before
writing:

```python
hold = await view.hold_publication(owner="source-refactor", ttl=300)
print(hold.token, hold.expires_at)
```

Retain the token across calls, edit files normally, inspect, then call
`view.release_publication(token)` and build. The hold applies across processes
and expires after the requested seconds, up to 3600. Release or expiry lets the
live editor resume publication. A hold delays replacement artifacts while
source editing remains available. It does not make multi-file writes atomic.

Retain the `ViewDocument` from `view.read()` when an edit needs a source
checkpoint. To restore, read and review current content, then write checkpoint
content with `expected_revision=current.revision`. Preserve both versions when
a save conflicts. Keep durable checkpoint copies outside project build inputs.
A retained artifact keeps Preview available while failed source is repaired.
Recover an external overwrite from a retained source copy or version control.
