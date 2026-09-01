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

## Studio does not appear in Marimo

Open the notebook in an environment that contains both Marimo and Studio:

```console
uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox
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

React, Reveal.js, and Svelte creation require the Deno extra:

```console
uvx --from 'marimo-studio[deno]==0.1.0' marimo-studio view create dashboard \
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

## A coding agent cannot show or validate a view

`marimo_studio.agent.current_workspace()` requires a code-mode execution bound
to the current notebook and Studio tab. Run `view.show()` in its own execution,
wait for the selected view to render, then request browser validation in a new
execution.

For terminal automation, pass a running Studio URL to `marimo-studio view show`
or browser validation. Select the intended browser client when several Studio
tabs are connected.

## A static export fails

Build the production profile and validate before exporting:

```console
marimo-studio view build dashboard \
  --target analysis.py \
  --profile production
marimo-studio validate dashboard --target analysis.py
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
the Studio and Marimo versions, the smallest reproduction, and redacted output.
Report suspected vulnerabilities through the [security
policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
