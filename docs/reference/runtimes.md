---
title: Runtime behavior
description: Server, WebAssembly, preview, run-mode, and static-export execution contracts.
---

# Runtime behavior

Studio presents the selected view through a server-backed Marimo kernel or a
WebAssembly worker.

| Presentation         | Notebook execution                  | Session                                   |
| -------------------- | ----------------------------------- | ----------------------------------------- |
| Server preview       | Editor's Python kernel              | Shared with the current edit session      |
| WebAssembly preview  | Pyodide worker                      | Separate notebook instance in the browser |
| Server run mode      | Python kernel in the Marimo process | Isolated per browser                      |
| WebAssembly run mode | Pyodide worker                      | Isolated per browser                      |
| Static export        | Pyodide worker                      | Created when the exported page opens      |

## Authoring runtime continuity

The Studio workspace keeps the native editor and each prepared preview
runtime mounted while you switch among **Notebook**, **Build**, **Preview**,
and **HTML & CSS**. Changing the workspace arrangement preserves the kernel,
control state, widgets, and browser state owned by those runtimes.

CSS and script-free HTML saves update the authored page around the mounted
runtime. An authored executable script or module change reloads the view
document so its browser lifecycle starts from the new source.

Public query parameters remain aligned among the Studio route, native editor,
and active preview. The notebook therefore observes the same query-driven
state while you compare authoring surfaces and runtimes.

## Server <Badge type="info" text="Python" />

The server runtime uses the active Marimo process. Use it for Python packages,
local files, databases, credentials, server-side network access, native
controls, and anywidgets.

In edit mode, the preview joins the editor's Python session. In run mode, each
browser receives an isolated Marimo kernel. Set `preserve_session = true` when
a manual refresh should reconnect to the browser's current run-mode kernel and
the serving process can retain that session.

## WebAssembly <Badge type="tip" text="Browser" />

The WebAssembly runtime starts a separate notebook instance in a Pyodide
worker. Notebook source, dependencies, public files, and data requested by the
notebook must be available to the browser.

Studio synchronizes JSON-compatible values from matching native Marimo
controls between prepared preview runtimes. Each runtime then evaluates its
own reactive graph. Control identity uses the control's cell and its position
inside that cell. Construct matching controls in the same order when a view
needs cross-runtime synchronization.

Anywidget state remains in the runtime that created its model. Python objects
that cannot cross the JSON boundary remain in their originating runtime.

## Static export <Badge type="warning" text="Public source" />

`marimo-studio export` writes one view, the notebook source, Studio browser
assets, the notebook's `public/` directory, and generated static cell
fragments. The exported page starts the notebook in a Pyodide worker.

::: warning Review the public export boundary
The notebook source is visible to site visitors. Its dependencies must install
in Pyodide. External data, modules, fonts, images, and icon sources must be
reachable from the browser.
:::

Use [Run, export, and share](../guide/run-and-share.md) for deployment commands.
[Notebook configuration](configuration.md) defines `runtime`, `runtimes`,
`preserve_session`, and `show_cell_logs`.
