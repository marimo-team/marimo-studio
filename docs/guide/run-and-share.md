---
title: Run or export a view
description: Run a view with Python or WebAssembly, or export prepared results as a static directory.
---

# Run or export a view

Runtime chooses where notebook code executes. Delivery chooses how visitors
receive the view.

| Runtime                       | Choose it when                                                                                                                    |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Python**<br>`server`        | The notebook needs server files, credentials, native packages, or a live service                                                  |
| **Browser**<br>`wasm`         | Visitors should compute new states in a [Pyodide](https://pyodide.org/) Python worker, using browser-compatible packages and data |
| **Prepared**<br>`zero-python` | Visitors should select among precomputed states and receive results while notebook source stays on the producer                   |

`marimo run` serves Python or Browser from a live process. Studio's editor can
preview all three. Static export defaults to Prepared and also supports Browser.
Prepared executes Python during export. Browser executes Python through
[WebAssembly](https://webassembly.org/) in each visitor's browser.

An [anywidget](https://anywidget.dev/) is a custom browser interface connected
to a Python model. Prepared delivery replays the captured model and browser
behavior. Preflight reports widget or control behavior that requires live Python.

## Configure available runtimes

```toml
[tool.marimo-studio]
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm", "zero-python"]
```

`runtime` chooses the default. `runtimes` controls the choices shown in Studio
and accepted through `?runtime=`. `zero-python` adds a Prepared preview in the
editor. A live run-mode server accepts `server` and `wasm`, so the default must
be one of those two runtimes.

Use the Python runtime for native packages, private files, databases, or server
credentials. Use the Browser runtime when the notebook and its data can run in
Pyodide and the visitor should compute locally. Its packages and data sources
must be reachable from that browser.

::: warning Browser visitors receive notebook source
The Browser runtime receives the saved notebook, compatible dependencies, and
public files. Keep credentials and server-owned code in the Python runtime.
Each external dataset must be reachable from the visitor's browser.
:::

## Run a live view locally

Start with the launch command printed by `view create` and replace `marimo edit`
with `marimo run`, keeping its environment options and sandbox flag. For a
notebook owned by a Python project, Studio composes project and existing inline dependencies,
sources, indexes, and Python constraints. Retaining those options preserves
that complete environment. For a project notebook with no inline dependencies:

```console
uv run --with marimo-studio --project . marimo run analysis.py --no-sandbox
```

A standalone notebook whose view uses the default Vanilla provider runs with:

```console
uv run --with marimo-studio marimo run analysis.py \
  --sandbox \
  --headless \
  --host 127.0.0.1 \
  --port 8000
```

The default view opens at `http://127.0.0.1:8000/`. A view named `report`
opens at `http://127.0.0.1:8000/report/`.

For browser automation, obtain the view's top-level URL:

```console
marimo-studio view preview report --target analysis.py \
  --runtime server --server http://127.0.0.1:8000
```

Open the URL with your preferred browser tool. Wait for
`html[data-marimo-studio-state="ready"]`, then assert the expected content and
interactions. Check console errors, failed requests, and screenshots. The HTML
attribute `data-marimo-studio-revision` identifies the committed presentation.
Use `--exact` for a checkpoint that returns HTTP 409 if the revision changes
or current view source is unbuilt or failed.

Authentication and the document sandbox apply to this separate presentation.
Keep the notebook session open when testing an edit-mode server.

Run `marimo-studio status --target analysis.py --json` when a project uses
additional view providers. Its `launch_requirements` list contains the Studio
and provider environment required by `marimo run`. Reviewing status can
resolve, install, and import provider packages declared by the project.

Use [Deploy a live Python view](deploy.md) before exposing the process to other
clients.

## Export a prepared static view

Build the production profile and prepare every projected result for the
default input state:

```console
marimo-studio view preflight dashboard \
  --target analysis.py

marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard
```

Preflight reports projection portability, prepared-state progress, and browser
artifact references without publishing a destination. Export repeats those
checks against the exact staged directory before committing it. Python executes
while either Zero-Python command runs.

::: tip Publish without sharing Python source
The Prepared runtime keeps the Python notebook and cell source on the machine
that runs the export. The static directory contains the production view,
prepared outputs, runtime metadata, and files placed in the notebook's
`public/` directory. The browser reads that publication without starting
Python. Cell names, IDs, and code hashes remain as provenance, while notebook
source and cell bodies are not serialized into the export.

See [`marimo-export`](https://github.com/marimo-team/marimo-export) for the
publication format and browser reader.
:::

Export and preflight flush progress as it arrives, including when the CLI
re-enters a project environment. Long operations emit a heartbeat every five
seconds with phase, elapsed time, state name, and the latest cache evidence.
`--json` keeps the terminal result on stdout and progress on stderr as JSONL.
Unknown state or cache evidence is `null`. The current export API does not expose
an active notebook cell, so the heartbeat's `cell` is `null`.

Each Zero-Python export uses the authored notebook's `__marimo__/cache/`
directory. [marimo's native cell cache](https://docs.marimo.io/api/caching/)
decides which authored cells can be restored across states, views, and later
export commands. `marimo-export` retains the resulting portable states in its
configured export repository. An exact later export can reuse that prepared
generation before starting the notebook. Set `MARIMO_EXPORT_REPOSITORY` to
choose the repository directory.

Prepared publication identity includes the saved notebook document. Changing a
Python control label therefore creates a new publication and walks the prepared
states again, even when marimo restores analytical cells from cache. Keep
presentation-only headings and labels in view source when they should change
independently of notebook computation. View-only edits can reuse the prepared
notebook states while Studio rebuilds the presentation artifact.

The repository stores verified portable publications. marimo remains the
owner of computation cache keys, invalidation, serialization, and restoration.
Use `mo.watch.file` in an upstream notebook cell when a result depends on file
contents that can change independently of notebook source.

Add `states.yaml` to the view project when visitors can change notebook
controls. The file declares the view's prepared state space. `matrix` expands
the Cartesian product of its accepted frontend values:

```yaml
schema: marimo-export.states.v1
default_state: matrix-000000
matrix:
  minimum_magnitude: [2.5, 3.0, 4.0]
  review_status:
    - [All statuses]
    - [reviewed]
```

The example prepares six states. Sliders accept numbers. A marimo dropdown's
frontend value is a one-item array, as shown for `review_status`. Use `states`
when the valid combinations are not a Cartesian product:

```yaml
schema: marimo-export.states.v1
default_state: overview
states:
  overview:
    minimum_magnitude: 2.5
    review_status: [All statuses]
  reviewed:
    minimum_magnitude: 4.0
    review_status: [reviewed]
```

State keys name notebook inputs that affect the view's finite projection
targets. Studio rejects dynamic `data-marimo-allow="*"` mounts, non-portable
input values, duplicate matrix values, and policies larger than 10,000 states.
Use explicit rows for a sparse set of valid combinations. Browser-side filtering
of an exported table can stay in view code and does not need a prepared Python
state for every selection.

A control selects a complete prepared state. Its values and projected results
commit together. A missing state or failed asset load retains the preceding
display. Add the intended input combination to `states.yaml`, preflight, and
export again when visitors need another Python result.

Raise `--prepare-timeout` when preparing a large state set:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard \
  --prepare-timeout 600
```

Serve the complete directory over HTTP:

```console
python -m http.server --bind 127.0.0.1 --directory dist/dashboard
```

Open `http://127.0.0.1:8000/`. Upload the complete directory and keep its
relative paths intact.

::: warning Review executable browser content before publishing
Notebook `public/` files and prepared outputs are visible to visitors. Authored
JavaScript, widgets, and rendered output execute in the visitor's browser.
Studio places the provider-authored page in a sandboxed iframe with an opaque
origin, so it cannot read the hosting origin's cookies, storage, or same-origin
server data. Origin-sensitive browser APIs and cross-origin requests observe
that opaque origin.
:::

Remote view dependencies keep their network requirements. Allow their script,
connection, font, image, and data origins in the hosting
[Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP).
A static export is a relocatable HTTP directory, not an offline bundle.

Use `--force` after reviewing an existing destination that should be replaced.
Studio stages the export before replacing that directory.

## Export the WebAssembly runtime

Use `--runtime wasm` when visitors should run notebook code and recompute input
states that were not prepared during export:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard \
  --runtime wasm
```

The WebAssembly export contains saved notebook source and starts Python through
Pyodide in each visitor's browser. Its packages, data sources, scripts,
workers, and remote assets must be reachable from that browser.

## Export the notebook

Create a static record of notebook code and captured output:

```console
mkdir -p dist/notebook
marimo export html analysis.py \
  --sandbox \
  --output dist/notebook/index.html
```

Use this document when visitors should read the analysis as it ran during the
export. Use a Studio Prepared export for a finite set of interactive states or
a WebAssembly export for visitor-side Python execution.
