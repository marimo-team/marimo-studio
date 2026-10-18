---
title: Troubleshoot Studio
description: Diagnose view discovery, provider, source, build, projection, runtime, and browser failures.
---

# Troubleshoot Studio

Inspect the saved notebook's views and providers. Add `--json` for a script or
coding agent:

```console
uvx marimo-studio status --target analysis.py
uvx marimo-studio doctor
```

::: warning Review configured providers
Studio commands can resolve, install, import, and invoke provider packages
declared by the notebook or Python project. Review the saved dependencies and
each `view.toml` before operating an unfamiliar project.
:::

## Studio does not appear in marimo

Open the notebook in an environment that contains both marimo and Studio:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox --watch
```

Save an untitled notebook with **Save As** before you create the first view.
When Studio reports an unconfigured notebook or no view, run
`marimo-studio status --target analysis.py`.

## `marimo run` shows the notebook instead of a view

Run mode serves the notebook itself while its view root holds no view, and the
server logs a warning. `marimo-studio status` reports `needs-view` and the
folder it searched. Restore the views there, `studio/<notebook-stem>/` by
default, or point [`view_root`](../reference/configuration.md#project-settings)
at their folder. Studio 0.3 looks only in `__marimo__/studio/`, so after you
move views out of it, update the notebook's `marimo-studio` requirement as
[Upgrade from 0.3](../reference/compatibility.md#upgrade-from-0-3) describes.

## Studio reports a views folder conflict

Views live in `studio/<notebook-stem>/`. Their build state lives in
`__marimo__/studio/<notebook-stem>/<view>/.artifacts/`, or under `state_dir` or
`MARIMO_STUDIO_STATE_DIR`. `marimo-studio status` prints both folders. When
they collide, Studio stops with one of these errors:

| Error                                                                | Fix                                                                                                                                               |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Views exist in both `studio/<stem>/` and `__marimo__/studio/<stem>/` | Move the views you keep into `studio/<stem>/` and remove the older folder. See [Upgrade from 0.3](../reference/compatibility.md#upgrade-from-0-3) |
| The build state folder of a view holds another view project          | Move that view out of the folder named in the error                                                                                               |
| `view_root` is inside Studio's view build state                      | Move the views out of the build state folder                                                                                                      |
| A view contains Studio's view build state                            | Rename the view                                                                                                                                   |
| Studio cannot keep view build state in a folder                      | Replace the link or file named in the error with a folder                                                                                         |
| Could not create the view state directory                            | Make it writable for the account that runs Studio                                                                                                 |
| `MARIMO_STUDIO_STATE_DIR` must be an absolute path                   | Set an absolute path, or leave it empty                                                                                                           |
| `state_dir` must be a non-empty relative path                        | Set a folder inside the project, or use `MARIMO_STUDIO_STATE_DIR`                                                                                 |

For a conflict between views folders and build state, choosing another
[build state location](../reference/configuration.md#build-state-location)
also resolves it.

## A starter is unavailable

Inspect its view provider and setup action:

```console
uvx marimo-studio doctor marimo-studio/react
uvx marimo-studio starters --target analysis.py
```

React, Reveal.js, Svelte, and Notebook Kit starters need the Deno extra:

```console
uvx --from 'marimo-studio[deno]' marimo-studio view create dashboard \
  --target analysis.py \
  --starter marimo-studio/react:default
```

The Quarto starter needs `quarto`, from `pixi global install quarto`. When
`starters` reports
`Studio found Quarto in a pixi or conda environment that is not activated.`,
start marimo through `pixi run` or inside `pixi shell`. Restart marimo after
the install.

The LaTeX starter needs [Tectonic](https://tectonic-typesetting.github.io/), a
self-contained TeX engine. Declare it in the notebook's
[pixi](https://pixi.prefix.dev/) metadata as [LaTeX](formats.md#latex) shows,
and open the notebook with `--sandbox=pixi`. When the starter reports
`The notebook's pixi environment is unavailable`, the rest of the reason is
pixi's error. Fix it, and Studio installs the environment again within a
minute. `pixi global install tectonic` works for every notebook after a marimo
restart.

Keep a third-party provider distribution in the notebook or Python project
dependencies, because Studio derives the provider requirement from each saved
`view.toml`.

## A LaTeX build reports `latex-compile-unfinished`

The first compile downloads the document's TeX packages and outlasted the
build's 120 second budget. Build again to continue from the downloaded
packages, or run this once from the view project with no time limit:

```console
tectonic -X compile main.tex
```

A document that never finishes, such as one with a recursive macro, reports
the same code. If that command still runs past 120 seconds after the download,
fix the document.

## A Source save does not update Preview

Inspect and build the selected view:

```console
marimo-studio view inspect dashboard --target analysis.py
marimo-studio view build dashboard --target analysis.py
```

**Build failed** means Preview still shows the last successful artifact. Fix
the source-located diagnostic and build again. If another author saved first,
compare **Your edits** with **Saved version**, and use the reported recovery
file before overwriting an uncertain replacement.

## A Source document is missing

The view provider controls the Source catalog. Check `view.toml`, then inspect
the project. The Vanilla provider lists local CSS and JavaScript that
`index.html` references directly. React and Svelte providers list files under
their configured source roots. Edit other files with the provider's project
tools, then inspect again.

## A notebook result is missing

Validate saved source and target names:

```console
marimo-studio validate dashboard --target analysis.py
```

Then execute the complete notebook and check the selected projections:

```console
marimo-studio validate dashboard \
  --target analysis.py \
  --level runtime
```

Runtime validation runs every notebook cell, including file, network, and
database work, so use it with trusted notebooks. Check the named cell or
variable, the selector syntax, and the runtime diagnostic.

For a computed React or Svelte projection target, use a finite literal set or
add `data-marimo-allow="*"` at the dynamic host.

## Preview needs repair after an outside edit

The notebook file changed while the Studio server ran without `--watch`.
Restart it with the flag:

```console
uvx --with marimo-studio marimo edit analysis.py --sandbox --watch
```

On macOS, `--watch` misses changes when the notebook path passes through a
symlinked folder such as `/tmp`. Open the resolved path, such as
`/private/tmp/analysis.py`.

## Preview cannot reach the Studio server

Preview shows **The preview cannot reach the Studio server.** after requests
from its sandboxed frame fail for 10 seconds. Check that the server runs. The
frame's requests carry no cookies, so a login proxy that requires a cookie
rejects them. For trusted notebooks and views, set
`MARIMO_STUDIO_TRUSTED_SERVER_RUNTIME=1` and restart, as
[Run as an ASGI application](deploy.md#run-as-an-asgi-application) describes.
In marimohub, follow
[Serve Preview behind a sign-in](marimohub.md#serve-preview-behind-a-sign-in).

## The Browser runtime does not start

The notebook's dependencies must run in Pyodide, and the visitor's browser must
reach notebook data, package indexes, runtime assets, and remote view
dependencies that the host's content security policy allows. Use the Python
runtime when the notebook needs native packages, local files, databases, or
server credentials.

### `runtime-config-too-large`

The Browser runtime configuration exceeds 16 MiB of UTF-8 JSON. Use finite
projection targets or reduce saved notebook source, then retry.

## A coding agent cannot inspect a view

`marimo_studio.agent.current_workspace()` needs a code-mode execution bound to
the current notebook and Studio tab, with the edit-mode session open. Run
`view.show()` in its own execution to activate the view. To check the page,
get `await view.preview_url(runtime="server")`, finish the execution, then
open the URL with a browser tool and wait for
`html[data-marimo-studio-state="ready"]`. Waiting inside code mode can block
the computations the page needs. If readiness stalls, read the visible status,
console errors, and failed requests.

If the preview asks you to run changed cells, run them in the live notebook or
use **Run all**, then retry. Building and validating the view leave the live
notebook's execution state unchanged.

If the page shows an earlier edit, check freshness with `view inspect`. An
exact preview URL returns HTTP 409 once the view's revision changes or its
source is unbuilt or fails to build, so build the source and request a fresh URL. See
[`preview_url()`](../reference/python-api.md#preview-url) and
[`marimo-studio view preview`](../reference/cli.md#marimo-studio-view-preview).

## A static export fails

Build the production profile and validate before exporting:

```console
marimo-studio view build dashboard \
  --target analysis.py \
  --profile production
marimo-studio validate dashboard --target analysis.py
```

For a Prepared export, give every projection site finite targets and use
accepted frontend values in `states.yaml`. Raise `--prepare-timeout` past its
30 second default when the states take longer to execute:

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard \
  --prepare-timeout 600
```

Review an existing output directory before using `--force`. Serve the complete
export over HTTP with its relative paths intact.

## Collect a diagnostic report

```console
marimo-studio status --target analysis.py --json
marimo-studio doctor --json
marimo-studio view inspect dashboard --target analysis.py --json
marimo-studio validate dashboard --target analysis.py --json
```

These reports omit notebook and view source but can contain absolute paths and
diagnostic text. Redact credentials, private paths, hostnames, and sensitive
diagnostics before you share them.

Open a [GitHub issue](https://github.com/marimo-team/marimo-studio/issues) with
the Studio and marimo versions, the smallest reproduction, and redacted output.
Report suspected vulnerabilities through the
[security policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
