---
title: View projects and artifacts
description: Authored frontend files, the view manifest, and generated browser artifacts.
---

# View projects and artifacts

A view is one directory beside its notebook:

```text
__marimo__/studio/analysis/
  .gitignore
  dashboard/
    view.toml
    index.html
    .artifacts/  generated
```

The default starter needs one authored HTML file. Other starters may add any
source tree and native tool configuration their build requires.

## Manifest

Studio writes `view.toml`:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

Explicit provider overrides live under `[options]`:

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "web/report.html"
```

Revision-aware manifest writes can update `[options]`. The `provider` key
remains fixed for the lifetime of the view. Create another view to choose a
different provider.

The manifest stores durable project choices. Starter identity and default
option values are not repeated there.

## Source documents

The selected provider reports the text documents shown in Source. Each record
has a project-relative path, language, `edit` or `read` access, and an optional
label. Providers also report one input scope, mount declarations, diagnostics,
and a build fingerprint. Studio enumerates the input scope for revisions,
snapshots, and file watching.

```console
marimo-studio view inspect dashboard --target analysis.py --format json
```

Agent and CLI inspection prepend the core `view.toml` manifest to the provider
document catalog. Source displays the provider-declared authoring documents.

Studio exposes ordinary source files. An accepted write compares the loaded
ETag, preserves the file mode, and atomically replaces the file in the same
directory. A conflicting browser keeps its unsaved buffer and receives the
current revision.

## Build and publication

```console
marimo-studio view build dashboard --target analysis.py
```

Studio:

1. Inspects the current project.
2. Copies declared inputs into an immutable snapshot.
3. Builds browser files in generated staging.
4. Rejects the candidate if live inputs changed.
5. Validates paths, symlinks, limits, the entry document, and public files.
6. Publishes an immutable content revision and updates the profile pointer.

The `development` profile backs live authoring. The `production` profile backs
run mode and export. A failed build retains the last valid publication.

## Generated files

`.artifacts/` contains replaceable build output for one view. The workspace
`.gitignore` ignores it together with `.locks/`.

Commit `view.toml`, authored source, native configuration, and dependency lock
files. Studio recreates `.artifacts/` during a build. Delete the directory and
build again when generated state needs a clean reset.

## Serving

Studio serves the last valid build with stable cache validators. A normal build
repairs missing or corrupt generated state from authored source.

[Frontend extension API](provider-api.md) defines provider ownership.
[Projection reference](projections.md) defines notebook result mounts.
