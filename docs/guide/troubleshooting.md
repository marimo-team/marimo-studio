---
title: Troubleshoot Studio
description: Diagnose view discovery, provider, source, build, projection, runtime, and browser failures.
---

# Troubleshoot Studio

Start with the saved notebook and inspect its configured views and providers:

```console
uvx marimo-studio status --target analysis.py
uvx marimo-studio doctor
```

Use `--json` when a script or coding agent will read the result.

::: warning Review configured providers
Studio commands can resolve, install, import, and invoke provider packages
declared by the notebook or Python project. Review the saved dependencies and
each `view.toml` before operating an unfamiliar project.
:::

## Studio does not appear in marimo

Open the notebook in an environment that contains both marimo and Studio:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox
```

Save an untitled notebook with **Save As**, then create the first view against
the saved path. Run `marimo-studio status --target analysis.py` when Studio
reports an unconfigured notebook or a configured notebook with no view.

## A starter is unavailable

Inspect its view provider and setup action:

```console
uvx marimo-studio doctor marimo-studio/react
uvx marimo-studio starters
```

React, Reveal.js, Svelte, and Notebook Kit creation require the Deno extra:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create dashboard \
  --target analysis.py \
  --starter marimo-studio/react:default
```

After creation, Studio derives the provider requirement from the saved
manifest. Keep a third-party provider distribution in the notebook or Python
project dependencies.

## A Source save does not update Preview

Inspect and build the selected view:

```console
marimo-studio view inspect dashboard --target analysis.py
marimo-studio view build dashboard --target analysis.py
```

**Build failed** means Preview still shows the last successful artifact.
Repair the source-located diagnostic and build again.

If another author saved first, compare **Your edits** with **Saved version**.
Use the reported recovery file before overwriting an uncertain replacement.

## A source document is missing

The view provider controls the Source catalog. Check `view.toml`, then inspect
the project. For Vanilla HTML, local CSS and JavaScript appear after
`index.html` references them directly. React and Svelte providers discover
files under their configured source roots.

Use the provider's project tools for files outside the editable catalog, then
inspect again.

## A notebook result is missing

Validate saved source and target names:

```console
marimo-studio validate dashboard --target analysis.py
```

Execute the complete notebook, then check the selected projections:

```console
marimo-studio validate dashboard \
  --target analysis.py \
  --level runtime
```

Runtime validation can perform file, network, database, and other work from any
notebook cell. Use it with trusted notebooks. Check the named cell or variable,
selector syntax, and runtime diagnostic.

For a computed React or Svelte projection target, either use a finite literal
set or add `data-marimo-allow="*"` at the dynamic host.

## The Browser runtime does not start

The notebook's dependencies must run in Pyodide. The visitor's browser must
reach notebook data, package indexes, runtime assets, and remote view
dependencies allowed by the hosting content security policy.

Switch to the Python runtime when the notebook requires native packages, local
files, databases, or server credentials.

### `runtime-config-too-large`

Studio caps the complete Browser runtime configuration at 16 MiB of UTF-8 JSON.
Notebook source and broad projection declarations are common contributors. Use
finite projection targets or reduce saved notebook source before retrying.

## A coding agent cannot inspect a view

`marimo_studio.agent.current_workspace()` requires a code-mode execution bound
to the current notebook and Studio tab. Run `view.show()` in its own execution
to activate the view. For direct browser inspection, get
`await view.preview_url(runtime="server")`, finish the execution, and open the
returned URL with a browser tool. Keep the edit-mode notebook session open.

For terminal automation, use `marimo-studio view preview dashboard --runtime
server --server http://127.0.0.1:8000 --target analysis.py`. Wait for
`html[data-marimo-studio-state="ready"]` in the browser, then check the expected
content. If readiness stalls, read the visible status or error and inspect
console errors and failed requests before repeating the wait or restarting.
Controls that recompute notebook output
need browser automation controlled outside that notebook kernel. Waiting
synchronously inside code mode can block those computations.

If the preview asks you to run changed notebook cells, execute those cells in
the live notebook or use marimo's **Run all** action, then retry the preview.
Building the view, checking notebook syntax, and isolated runtime validation
leave the live notebook's execution state unchanged.

If the page works but shows an earlier edit, inspect source and build freshness
with `view inspect`. A failed build retains the previous successful artifact.
An exact preview URL returns HTTP 409 when its presentation revision changes
or view source is unbuilt or failed. Repair and build current source, then
request a fresh URL.

## A static export fails

Build the production profile and validate before exporting:

```console
marimo-studio view build dashboard \
  --target analysis.py \
  --profile production
marimo-studio validate dashboard --target analysis.py
```

For a Prepared export, check that every projection mount has finite targets and
that `states.yaml` uses accepted frontend values. Increase
`--prepare-timeout` when the configured state set needs more than 30 seconds
to execute:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard \
  --prepare-timeout 600
```

Review an existing output directory before using `--force`. Serve the complete
export over HTTP and keep its relative paths intact.

## Collect a diagnostic report

```console
marimo-studio status --target analysis.py --json
marimo-studio doctor --json
marimo-studio view inspect dashboard --target analysis.py --json
marimo-studio validate dashboard --target analysis.py --json
```

These reports omit notebook and view source content. They can contain absolute
paths and provider or runtime diagnostic text. Redact credentials, private
paths, hostnames, and sensitive diagnostics before sharing them.

Open a [GitHub issue](https://github.com/marimo-team/marimo-studio/issues) with
the Studio and marimo versions, the smallest reproduction, and redacted output.
Report suspected vulnerabilities through the [security
policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
