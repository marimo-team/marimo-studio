---
title: Troubleshoot Studio
description: Diagnose view discovery, provider, source, build, projection, runtime, and browser failures.
---

# Troubleshoot Studio

::: warning Review configured providers
`status`, `view create`, `view inspect`, `view read`, `view write`, `view build`,
`view export`, and `validate` may resolve, install, and import provider packages
declared by the target notebook or project. Review its `view.toml` files and
Python dependencies before running these commands.

Reading or repairing `view.toml` uses Studio's provider-independent manifest
path in the current process.
:::

Start with the saved notebook and inspect its configured views:

```console
uvx marimo-studio status --target analysis.py
uvx marimo-studio doctor
```

Use `--json` when a script or coding agent will read the result.

## Studio does not appear in Marimo

Open the notebook in an environment that contains both Marimo and Studio:

```console
uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox
```

Run `marimo-studio status --target analysis.py` when Studio reports no configured
view. The result identifies the active configuration file and the command that
creates the first view.

## A frontend choice is unavailable

Inspect its provider and setup action:

```console
uvx marimo-studio doctor marimo-studio/react
uvx marimo-studio starters
```

React, Reveal.js, and Svelte require the Deno extra during view creation. For
0.1.0, run their create commands through
`uvx --from 'marimo-studio[deno]==0.1.0'`.

After creation, `status`, `view create`, `view inspect`, `view read`, `view
write`, `view build`, `view export`, and `validate` derive the Deno requirement
from the saved provider key and prepare it through `uv`. Use the printed launch
requirements when opening the notebook through `marimo edit` or `marimo run`.

For a third-party key such as `acme-views/report`, keep an active `acme-views`
requirement in the notebook or project dependencies.

## A source save does not update Preview

Check the selected view:

```console
uvx marimo-studio view inspect dashboard --target analysis.py
uvx marimo-studio view build dashboard --target analysis.py
```

Studio keeps the last successful artifact visible after a failed build. Repair
the source-located diagnostic, then build again.

When another browser, editor, or agent saved first, Studio keeps the current
buffer and reports a source conflict. Compare the saved file with the current
buffer before choosing which content to keep.

## A notebook result is missing

Validate saved source and projection names without executing the notebook:

```console
uvx marimo-studio validate dashboard --target analysis.py
```

Use runtime validation when the name is correct and the result depends on
notebook execution:

```console
uvx marimo-studio validate dashboard \
  --target analysis.py \
  --level runtime
```

Runtime validation can perform the notebook's configured file, network,
database, and data access.

## Browser execution does not start

WebAssembly execution requires dependencies that run in Pyodide. The visitor's
browser must reach the notebook's external data and the remote WebAssembly
runtime origins allowed by the hosting content security policy.

Switch to the Python runtime when the notebook requires native packages, local
files, databases, or server credentials. Read [Run or publish a
view](run-and-share.md) before deploying either runtime.

### Studio reports `runtime-config-too-large`

Studio caps the complete browser runtime payload at 16 MiB of UTF-8 JSON.
Notebook source and broad projection declarations are common contributors.
Replace wildcard projection declarations with finite targets or reduce the
saved notebook source, then retry the Browser runtime or static export.

## A coding agent cannot show or validate a view

`marimo_studio.agent.current_workspace()` requires a code-mode execution bound
to the current notebook and Studio tab. Call `view.show()` in its own execution,
wait for the selected view to render, then request browser validation in another
execution.

For terminal automation, pass a running Studio URL to `marimo-studio view show`
or browser validation. When several Studio tabs are connected, pass the intended
browser client ID reported by the command.

## A static export fails

Inspect and validate the production view before exporting:

```console
uvx marimo-studio view build dashboard \
  --target analysis.py \
  --profile production
uvx marimo-studio validate dashboard --target analysis.py
```

Review an existing output directory before replacing it with `--force`. A static
export contains the saved notebook source, view files, and notebook `public/`
files. Host it on a dedicated origin and serve the complete directory over HTTP.

## Collect a diagnostic report

Capture machine-readable state:

These commands can load or invoke configured providers with the current user's
authority. Review installed provider packages before collecting diagnostics.

```console
uvx marimo-studio status --target analysis.py --json
uvx marimo-studio doctor --json
uvx marimo-studio view inspect dashboard --target analysis.py --json
uvx marimo-studio validate dashboard --target analysis.py --json
```

These reports omit notebook and view source content. They can contain absolute
paths and arbitrary provider or runtime diagnostic text. Review every field and
redact credentials, private paths, hostnames, and sensitive diagnostic text
before sharing the report in a public issue.

## Get project support

Open a [GitHub issue](https://github.com/marimo-team/marimo-studio/issues) with
the affected Studio and Marimo versions, the smallest reproduction, and redacted
diagnostic output. Report suspected vulnerabilities through the private path in
the [security policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
