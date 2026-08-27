---
title: Live authoring
description: Edit notebook and frontend source, switch views, build, and compare runtimes in one Marimo session.
---

# Live authoring

Open a configured notebook:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Opening a configured Studio workspace starts the notebook after the native
editor session connects. Preview stays in `connecting` until that first run
finishes.

Studio adds four workspace modes:

- **Notebook** focuses the Marimo editor.
- **Develop** shows notebook, Source, and Preview together.
- **Preview** focuses the selected rendered view.
- **Source** focuses frontend documents.

The selected notebook kernel remains active while modes and views change.

## Edit source

Source tabs come from provider inspection. Each document reports its language
and `edit` or `read` access. Studio remembers the active document for each view.

Writes use file ETags. When another browser or editor saves first, Studio shows
the disk content and keeps the exact local buffer. Reload, copy, or retry after
reviewing the conflict.

## Build

Source changes queue one development build for the latest view generation.
Several browser windows share that publication work. Obsolete generations are
coalesced.

A successful build commits the complete document, styles, runtime config, and
mount preparation together. A failed build leaves the previous page intact and
shows the diagnostic beside Source.

```console
uvx marimo-studio view build dashboard --target analysis.py
```

## Switch views

The view selection transaction:

1. Flushes pending source.
2. Synchronizes the notebook query.
3. Prepares the target preview.
4. Commits the selected view.
5. Hydrates the target Source session.
6. Updates route, layout, and focus.

A newer selection supersedes older work. Returning to a warm, non-evicted
preview frame reuses the current runtime session without a document navigation.

## Compare runtimes

Use the runtime selector to compare the Python-backed Server runtime with a
compatible browser-worker execution. Studio keeps a bounded prepared-frame
cache for each runtime. Up to three recent Server views stay warm with the
active Python-backed notebook session, while WebAssembly retains its selected
view's worker frame.

Preview runtime diagnostics use `connecting`, `synchronizing`, `ready`,
`degraded`, and `failed`. Details appear beside the state.

## Use several browser windows

Windows share authored files and published artifacts. Each window keeps its own
session, selected view, layout, and unsaved source buffer. Conflicting saves
produce one accepted ETag and one explicit conflict.

## Validate the current result

```console
uvx marimo-studio validate dashboard --target analysis.py --level browser \
  --server http://localhost:2718 \
  --browser-client CLIENT_ID
```

Exercise relevant controls and dynamic mounts before requesting browser
evidence.

[Views](views.md) covers view creation and removal. [Notebook
results](notebook-results.md) covers mount behavior.
