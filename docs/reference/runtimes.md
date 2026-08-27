---
title: Runtime behavior
description: Server, WebAssembly, preview, run-mode, and static-export execution contracts for published view artifacts.
---

# Runtime behavior

Studio presents a published view artifact through a server-backed Marimo
kernel or a WebAssembly worker.

| Presentation         | Notebook execution                  | Session                                   |
| -------------------- | ----------------------------------- | ----------------------------------------- |
| Server preview       | Editor's Python kernel              | Shared with the current edit session      |
| WebAssembly preview  | Pyodide worker                      | Separate notebook instance in the browser |
| Server run mode      | Python kernel in the Marimo process | Isolated per browser                      |
| WebAssembly run mode | Pyodide worker                      | Isolated per browser                      |
| Static export        | Pyodide worker                      | Created when the exported page opens      |

## Presentation revision

Each rendered view is bound to one saved notebook revision and one valid view
build. Studio carries that identity through runtime requests so a response from
an older view cannot update the current page. A browser refreshes when its
revision is no longer available.

## Authoring continuity

The Studio workspace keeps the native editor and prepared previews mounted
while you switch among **Notebook**, **Develop**, **Preview**, and **Source**.
Changing the workspace arrangement preserves the kernel, control state,
widgets, and browser state owned by those runtimes.

A Source save changes the view project. Studio inspects the provider inputs and
builds or reuses a development artifact before publishing the next
presentation. A build failure leaves the current published artifact available.
`marimo-studio view build` returns the provider or artifact error for repair.

Public query parameters remain aligned among the Studio route, native editor,
and active preview. The notebook observes the same query-driven state while
you compare authoring surfaces and runtimes.

## Server <Badge type="info" text="Python" />

The server runtime uses the active Marimo process. Use it for Python packages,
local files, databases, credentials, server-side network access, native
controls, and anywidgets.

In edit mode, the preview joins the editor's Python session. In run mode, each
browser receives an isolated Marimo kernel. With `preserve_session = true`, a
manual refresh reconnects when the canonical public notebook query matches the
query that created the kernel. Private Studio routing and transport keys do not
affect the match. A different public query starts a fresh kernel and
presentation. The serving process must retain the session being reused.

Mounted results resolve against the saved notebook before Studio reads a value,
formats an output, or attaches a complete cell result. The kernel verifies the
selected live session again immediately before execution.

## WebAssembly <Badge type="tip" text="Browser" />

The WebAssembly runtime starts a separate notebook instance in a Pyodide
worker. Notebook source, compatible dependencies, public files, and data
requested by the notebook must be available to the browser.

The worker loads the saved notebook and initializes Studio's mount bridge. The
browser resolves each mounted target, then executes the required cells through
Marimo's queue.
Dynamic target changes schedule newly required cells. Unmounted or invalid
targets do not start independent notebook branches, and view revisions retain
the worker when the runtime instance is unchanged.

Bracketed selector keys follow JSON string syntax in Server and WebAssembly
runtimes.

Studio synchronizes JSON-compatible values from matching native Marimo
controls between prepared preview runtimes. Each runtime then evaluates its
own reactive graph. Control identity uses the control's cell and its position
inside that cell. Construct matching controls in the same order when a view
needs cross-runtime synchronization.

Anywidget state remains in the runtime that created its model. Python objects
that cannot cross the JSON boundary remain in their originating runtime.

## Projection lifecycle

Literal hosts and provider-analyzed dynamic hosts use the same runtime
resolution path. A
host mount creates a projection instance. Changing `name`, `value`, or
`mo-value` resolves a replacement target. Unmounting the host releases its
instance and any final-owner runtime resources.

Every request carries its presentation revision, mount ID, instance ID, and
current target. Studio derives the result kind from the built declaration and
checks its allowed targets. See [Notebook result mounts](projections.md) for
the target and ownership contracts.

## Static export <Badge type="warning" text="Public source" />

`marimo-studio view export` builds or reuses the selected view's production
artifact. The export copies its browser files, then adds notebook source,
Studio browser assets, and the notebook's `public/` directory. The exported
page loads the notebook graph in a Pyodide worker and executes the dependency
closures requested by its mounted projection hosts. An independent branch with
browser-incompatible code remains dormant until that branch is selected.
`StaticExportResult.entrypoint` preserves the artifact's document path,
including nested paths, and runtime URLs are computed relative to that
document.

::: warning Review the public export boundary
The notebook source is visible to site visitors. Its dependencies must install
in Pyodide. External data, modules, fonts, images, and icon sources must be
reachable from the browser.
:::

Use [Run, export, and share](../guide/run-and-share.md) for deployment commands.
[Notebook configuration](configuration.md) defines `runtime`, `runtimes`,
`preserve_session`, and `show_cell_logs`.
