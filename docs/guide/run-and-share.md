---
title: Run or export a view
description: Serve a view from Python, run it in the visitor's browser, or export prepared results as a static site.
---

# Run or export a view

A [runtime](../reference/glossary.md#runtime) decides where notebook code runs
when someone opens a view. The same view project serves all three, so you
choose per deployment between live Python, Python in the visitor's browser, and
a static site with saved results:

| Runtime                       | Python runs                                                        | Choose it when                                                               |
| ----------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| **Python**<br>`server`        | On a server, for each session                                      | The notebook needs private files, credentials, native packages, or a service |
| **Browser**<br>`wasm`         | In each visitor's browser, through [Pyodide](https://pyodide.org/) | Visitors should compute new states without a server                          |
| **Prepared**<br>`zero-python` | Once, on your machine, during export                               | Visitors pick among prepared states, and the notebook source stays private   |

`marimo run` serves the Python and Browser runtimes. `marimo-studio view
export` writes a static site with the Prepared runtime by default, or with the
Browser runtime. The Studio editor can preview all three.

Choose the runtimes a notebook offers in its configuration:

```toml
[tool.marimo-studio]
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm", "zero-python"]
```

`runtime` is the default and must be `server` or `wasm`, because it also
applies to `marimo run`. `runtimes` lists the choices in Studio and in the
`?runtime=` URL parameter. Adding `zero-python` adds a Prepared preview to the
editor.

::: warning The Browser runtime sends the notebook to visitors
Visitors receive the saved notebook source, its dependencies, and its public
files. Keep credentials and private code in the Python runtime, and make every
dataset reachable from the visitor's browser.
:::

## Run a live view

`view create` prints the launch command for the notebook. Replace
`marimo edit` with `marimo run` and keep the other options. For a standalone
notebook:

```console
uvx --with marimo-studio marimo run analysis.py --sandbox --host 127.0.0.1 --port 8000
```

For a notebook in a uv project:

```console
uv run --with marimo-studio --project . marimo run analysis.py --no-sandbox \
  --host 127.0.0.1 --port 8000
```

The default view opens at `http://127.0.0.1:8000/`, and a view named `report`
at `http://127.0.0.1:8000/report/`. When a project uses third-party view
providers, `marimo-studio status --target analysis.py --json` lists the
packages `marimo run` needs in `launch_requirements`.

Read [Deploy a live Python view](deploy.md) before you expose the process to
other people.

## Export a prepared static view

Check the view, then export it:

```console
uvx marimo-studio view preflight dashboard --target analysis.py
uvx marimo-studio view export dashboard --target analysis.py --output dist/dashboard
```

Both commands run the notebook. Preflight builds the view, prepares the
notebook results, and reports what will not work without Python, such as a
widget that needs a live kernel. It leaves `dist/` untouched. Export runs the
same checks on the staged site before it replaces `dist/dashboard`.
Pass `--force` to replace an existing folder.

::: tip The export keeps the notebook source private
The site holds the built view, the prepared results, and the files in the
notebook's `public/` folder. It holds no notebook code. Cell names and code
hashes remain as provenance.
[`marimo-export`](https://github.com/marimo-team/marimo-export) defines the
format and the browser reader.
:::

Serve the folder over HTTP and keep its relative paths intact:

```console
uv run --no-project python -m http.server --bind 127.0.0.1 --directory dist/dashboard
```

The site is relocatable but not offline. Remote scripts, fonts, maps, and data
keep their network requirements, and the host's
[Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
must allow their origins.

### Prepare states

A prepared export answers each control change from a saved state. During
export, Studio runs the notebook once for each
[prepared state](../reference/glossary.md#prepared-state) and saves every
result. In the browser, a control change loads the saved state that matches
the page's control values, so the visitor sees the notebook's own results and
no Python runs. A value the export did not prepare has no saved state, so the
page keeps showing the previous one:

<llm-exclude>

<StudioPreparedStates />

</llm-exclude>

By default the export prepares one state: the notebook's initial control
values. To let visitors change controls, add `states.yaml` to the view project.
A `matrix` prepares every combination of the listed values:

```yaml
schema: marimo-export.states.v1
default_state: matrix-000000
matrix:
  minimum_magnitude: [2.5, 3.0, 4.0]
  review_status:
    - [All statuses]
    - [reviewed]
```

This prepares six states. Keys name the notebook controls, and values are the
controls' frontend values: a number for a slider, and a one-item list for a
dropdown. List `states` by name when only some combinations make sense:

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

A control change loads a complete prepared state, so its values and results
change together. Export and preflight warn with `prepared-states-skip-control-values`
when the prepared values skip a value that a slider, number, dropdown, radio,
checkbox, or switch on the page can send, such as a slider step between two
listed values. Filtering a table that is already in the browser needs no
prepared state, so keep that logic in view code. A policy may list at most 10,000
states. Pass a larger `--prepare-timeout SECONDS` when a large state set takes
longer to prepare.

### Reuse earlier work

Export uses marimo's [cell cache](https://docs.marimo.io/api/caching/) in the
notebook's `__marimo__/cache/` folder, and `marimo-export` keeps finished
publications in its export repository, which `MARIMO_EXPORT_REPOSITORY` can
move. An unchanged notebook reuses its prepared states, and a change to view
source rebuilds the view only. Any change to the notebook file, even a control
label, prepares the states again, so keep presentation-only text in the view.
Wrap a file a result depends on with `mo.watch.file`, so a change to the file
invalidates the cache.

With `--json`, export and preflight print the final result on stdout and JSON
Lines progress on stderr, with a heartbeat every five seconds.

## Export a Browser view

```console
uvx marimo-studio view export dashboard --target analysis.py \
  --output dist/dashboard --runtime wasm
```

The site contains the notebook source and starts Python in each visitor's
browser, so visitors can reach any combination of control values. Its packages, data, and
remote assets must be reachable from the browser.

::: warning Review browser code before you publish
Prepared results, `public/` files, view scripts, and widgets all run or load in
the visitor's browser. Studio places the view in a sandboxed iframe with an
opaque origin, so view code cannot read the hosting site's cookies or storage.
:::

## Export the notebook itself

To publish the notebook as it ran, with its code and outputs, use marimo's own
export:

```console
uvx --with marimo-studio marimo export html analysis.py --sandbox --output dist/notebook/index.html
```
