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

Use the provider's native project tools for changes that Source does not own,
such as adding a React module, updating a Svelte dependency, or creating a
public asset. Reinspect the project after changing its file graph:

```console
marimo-studio view inspect dashboard --target analysis.py
marimo-studio view build dashboard --target analysis.py
```

The next Studio refresh receives the new catalog and artifact state. Keep
generated `.artifacts/` content under Studio's ownership.

Use [Choose a frontend](frontend-options.md) for provider-specific project
shapes and [Troubleshoot Studio](troubleshooting.md) for source, manifest, or
build diagnostics.
