---
title: Author with the live workspace
description: Move among the notebook, source, and preview while keeping runtime state and file changes in view.
---

# Author with the live workspace

Studio keeps the Marimo notebook, view source, and rendered page in one
workspace. Use the notebook for calculations and controls, edit the view as
ordinary web files, and inspect the result against the same live analysis.

Open a configured notebook:

```console
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

## Choose the surface for the current task

The main modes change the arrangement while keeping the underlying work
available.

| Mode           | What you see                                      | Use it for                                                              |
| -------------- | ------------------------------------------------- | ----------------------------------------------------------------------- |
| **Notebook**   | The native Marimo editor                          | Data access, transformations, metrics, controls, and reactive debugging |
| **Build**      | Notebook and selected preview side by side        | Connecting notebook behavior to the audience-facing page                |
| **Preview**    | The selected view at the available workspace size | Reading, interaction, and responsive review                             |
| **HTML & CSS** | `index.html`, `app.css`, and the preview          | Page structure, styling, and fast source feedback                       |

Open the workspace menu to arrange the notebook, source, and preview panes.
Drag the dividers to choose their proportions. Studio remembers the layout for
each view in the current browser. At narrow sizes, switch among the available
surfaces while keeping the same saved arrangement for a larger window.

Studio keeps the notebook frame and prepared preview runtimes mounted while
you move among modes. A mode change therefore preserves the live kernel,
control state, widget models, and browser state owned by each runtime.

## Edit in Studio or your editor

Open **HTML & CSS** to edit `index.html` and `app.css` in the browser. Studio
saves after a short pause and reports whether the active file is saving,
saved, changed on disk, in conflict, or in error.

The same files remain available to your regular editor:

```text
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        app.css
        app.js
```

An external save appears in the Studio source editor and preview. When the
browser and disk both changed from the same earlier revision, Studio keeps
both versions and asks you to choose:

| Action        | Result                                                   |
| ------------- | -------------------------------------------------------- |
| **Compare**   | Show the browser version beside the current disk version |
| **Use disk**  | Replace the browser buffer with the external edit        |
| **Keep mine** | Save the browser buffer against the latest disk revision |

Resolve the conflict before switching views or closing the workspace. This
keeps an external editor, a coding agent, and the browser from silently
overwriting one another.

## See each save at the right scope

Studio refreshes the smallest page boundary that can apply a source change
correctly.

| Change                                 | What you observe                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------------------- |
| `app.css`                              | The current page styles update while projections and runtime state remain mounted      |
| Script-free `index.html`               | The authored `#app-shell` is replaced around the mounted Marimo results                |
| `index.html` with executable scripts   | The view document reloads so the browser evaluates the authored script lifecycle again |
| A JavaScript module or imported module | The view document reloads and reads the new module graph                               |
| A notebook cell                        | Marimo reruns its reactive dependents and updates affected projections                 |

Each presentation refresh uses one complete source revision. If the notebook,
view files, or runtime configuration are still settling, the preview waits and
retries instead of presenting a mixed page.

::: tip Keep interactive state during layout work
Start with a script-free `index.html` when the page needs frequent structural
changes around controls, plots, or widgets. Add authored scripts when the view
needs browser behavior that justifies a full document lifecycle on save.
:::

## Compare execution environments

Choose a preview runtime from the Studio toolbar.

| Runtime         | What it gives you during authoring                                                                                                         |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Server**      | The selected view joins the native editor's Python session, including its packages, data access, controls, and outputs                     |
| **WebAssembly** | The notebook runs again in a browser worker, which previews the same view under the constraints used by browser delivery and static export |

Studio prepares configured preview runtimes so switching runtimes preserves
the state that belongs to each one. This makes it practical to compare a
server-backed page with its browser-executed version during the same authoring
session.

Native Marimo controls can synchronize JSON-compatible values between the
editor and prepared previews when the runtimes define matching controls in the
same cell order. Each runtime then evaluates its own reactive graph. Anywidget
models and Python objects remain with the runtime that created them.

[Runtime behavior](../reference/runtimes.md) defines the complete server,
WebAssembly, run-mode, and static-export contracts.

## Keep links and query-driven state aligned

View links work in both the workspace and the finished application:

```html
<a href="../executive/?region=emea">Open the EMEA brief</a>
```

Studio opens the target view and preserves the active workspace mode. Public
query parameters follow the notebook editor and active preview, so code that
uses Marimo query parameters observes the same audience selection across the
authoring surfaces.

Internal Studio coordination parameters stay out of the public query exposed
to notebook code. Treat the remaining query string as part of the view's
shareable state and test direct links as well as in-page navigation.

## Work safely with authored scripts

View HTML and JavaScript run as application code on the same origin as the
Marimo session. Give source-editing access to people and agents who are trusted
with the notebook, its credentials, and its data. Review third-party modules
and network-loaded assets before using them in a deployed view.

For a browser-facing deliverable, check the view in the environment where it
will run:

1. Change the controls that drive the main decision.
2. Switch every configured view and follow its direct links.
3. Compare Server and WebAssembly when both are delivery targets.
4. Exercise tables, plots, downloads, controls, and anywidgets.
5. Reload the page and verify the configured session behavior.
6. Inspect narrow and wide layouts, keyboard focus, failed requests, and the
   browser console.

Continue with [Use notebook results](notebook-results.md) for projection
choices, [Use HTML, CSS, and JavaScript](web-platform.md) for authored page
APIs, or [Run, export, and share](run-and-share.md) for delivery.
