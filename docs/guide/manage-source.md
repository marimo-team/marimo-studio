---
title: Manage view source
description: Understand the Source catalog, view manifest, build inputs, conflicts, and recovery files.
---

# Manage view source

Source shows the documents that the selected view provider exposes for a view
project. Each entry has a project-relative path, language, access mode, content,
and revision.

The catalog follows the provider and project. A Vanilla view may show
`index.html`, directly linked CSS and JavaScript, `AGENTS.md`, and `DESIGN.md`.
A React or Svelte project exposes its authored source and configuration while
keeping generated artifacts outside Source.

## Distinguish documents from build inputs

A **source document** is a file Studio can show in Source. A **build input** is
a file or directory whose content can affect the artifact. The sets overlap,
but they answer different questions.

For example, a React provider can expose `src/App.tsx` for editing, treat the
complete `src/` and `public/` directories as build inputs, and expose the lock
file as read-only. A lockfile records exact frontend dependency versions so the
same project resolves the same packages in later builds. The provider inspects
both sets before Studio starts a build.

Run a provider inspection from the terminal:

```console
marimo-studio view inspect dashboard --target analysis.py
```

## Edit `view.toml`

Every view project contains `view.toml`:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

The manifest records the view provider and explicit provider options. Studio
always makes `view.toml` available through its manifest path, including when
provider inspection fails. Repair an invalid provider key or option there, then
inspect or build the view again.

Starter identity is creation-time input. The saved manifest keeps the provider
contract that owns the project after creation.

## Keep project guidance with the view

Bundled starters create `AGENTS.md`, a project-local instruction file for
coding agents, with provider-specific guidance. Keep the project intent section
current when an agent will maintain the view.

Add `DESIGN.md` to record durable decisions such as audience, analytical job,
visual direction, interaction priorities, and approved libraries. Bundled view
providers include that file in Source when it exists.

## Resolve a concurrent save

Studio writes a document against the revision that Source loaded. When another
browser, editor, or agent saves first, Studio keeps your buffer and reports a
conflict.

- **Use saved version** loads the newer saved document.
- **Overwrite saved version with my edits** replaces it with the current
  buffer.

Compare **Your edits** with **Saved version** before choosing. A view switch
waits until the conflict is resolved.

When Studio reports a recovery file, that path contains the previous saved
content. Read it before retrying an interrupted or uncertain replacement.

## Edit outside Studio

Edit view source with your editor, patch tool, shell, or Studio. Use the project
root returned by `view inspect --json`. Provider inspection determines which
files appear in Source and which files affect builds, regardless of how they
were edited. Keep generated `.artifacts/` content under Studio's ownership.

Inspect and build after editing:

```console
marimo-studio view inspect dashboard --target analysis.py
marimo-studio view build dashboard --target analysis.py
```

Each inspection reads current disk content. Builds and validation also inspect
current source, so explicit commands can pick up changes even when a filesystem
notification was missed. The live editor watches for source changes and repairs.
A missing input or invalid source retains the last successful artifact while
Studio reports the affected path and repair action.

Inspection separates `project_revision`, the observed build inputs, from
`published_project_revision`, the inputs behind the retained artifact.
`latest_build` reports the latest attempt, including a failure, while `build`
identifies the retained successful artifact. Open `view.preview_url(runtime="server")`
with your browser and check the committed `data-marimo-studio-revision` on the
HTML document before asserting the rendered result.

### Coordinate a multi-file change

Hold publication while an edit passes through incomplete states:

```sh
marimo-studio view hold dashboard --target analysis.py \
  --owner source-refactor --ttl 300 --json > hold.json
```

Edit the files normally, inspect the result, then release the hold and build:

```sh
marimo-studio view inspect dashboard --target analysis.py
marimo-studio view release dashboard --target analysis.py \
  --token "$(jq -r .token hold.json)"
marimo-studio view build dashboard --target analysis.py
```

[jq](https://jqlang.org/manual/) extracts the release token from the JSON record.
Keep that record outside the view project's build inputs. A hold applies across
processes and keeps the existing publication available while source editing
continues. It expires after 300 seconds by default, with a maximum of 3600
seconds. Release or expiry lets the live editor reconcile current source and
resume publication. Source edits remain on disk.

Choose a hold duration that covers the edit. Automatic change detection can
observe a valid intermediate state during a multi-file save. A hold delays
publication, but it does not make filesystem writes atomic or protect one
external writer from another.

### Compare and recover source

Keep an inspection before editing and compare a fresh inspection afterward:

```python
from marimo_studio.authoring import open_workspace

view = open_workspace("analysis.py").view("dashboard")
before = await view.inspect()
# Edit source files, then run the remaining statements in the same execution.
after = await view.inspect()
if before.files_complete and after.files_complete:
    print(after.changes_since(before).to_dict())
```

The comparison reports added, modified, and deleted files within the provider's
source and build-input inventory. Incomplete discovery is reported through
`files_complete=False` and diagnostics. Repair the manifest or provider issue
before comparing inventories.

To keep a document checkpoint, retain the `ViewDocument` returned by
`view.read()`. Before restoring its content, read the current document and
review both versions:

```python
checkpoint = await view.read("index.html")
# Retain checkpoint while editing, then review the current document.
current = await view.read("index.html")
print(current.content)
await view.write(
    "index.html",
    checkpoint.content,
    expected_revision=current.revision,
)
```

The restore uses the current revision as its write precondition. Another save
raises `SourceConflictError`, preserving that newer content. Persist checkpoint
content outside the view project when recovery must survive the editing
process. Recovering an external overwrite requires a retained copy or version
control. Retaining a successful artifact keeps Preview available but does not
restore authored source.

Use [Choose a frontend](frontend-options.md) for provider-specific project
shapes and [Troubleshoot Studio](troubleshooting.md) for source, manifest, or
build diagnostics.
