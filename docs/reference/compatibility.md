---
title: Compatibility and support
description: Supported Python, Marimo, Deno, uv, browser, runtime, release, provider, deployment, and security contracts for Marimo Studio 0.1.
---

# Compatibility and support

Marimo Studio 0.1.1 begins the first documented compatibility line. The
notebook-to-view workflow, projection elements, and last-successful build
behavior are supported product contracts. Before 1.0, CLI, Python, provider,
and saved configuration contracts may change between minor releases.

Add Studio to the notebook or project dependencies:

```toml
dependencies = ["marimo-studio"]
```

## Upgrade from 0.0.6

Version 0.1.1 introduces explicit view manifests and a notebook-bound authoring
API. Update saved view projects and automation before opening them with 0.1.1.

Add this `view.toml` to each existing 0.0.6 view directory:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

Keep the existing `index.html` and any CSS or JavaScript files it references.
Then run `marimo-studio status --target analysis.py`. Studio discovers the view,
assigns its owner record, and reports its Source documents. Commit `view.toml`
and the generated `.owners/` records with the view project.

Update command and Python callers with these replacements:

| 0.0.6 contract                                                                 | 0.1.1 replacement                                                                      |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `marimo-studio inspect TARGET --display`                                       | `marimo-studio notebook inspect --target TARGET --output-expressions`                  |
| `marimo-studio bind TARGET --cell 12 --as summary`                             | `marimo-studio notebook bind summary --target TARGET --cell 12`                        |
| `marimo-studio view add TARGET --name report`                                  | `marimo-studio view create report --target TARGET`                                     |
| `marimo-studio view list TARGET`                                               | `marimo-studio status --target TARGET`                                                 |
| `marimo-studio view remove TARGET --name report`                               | `marimo-studio view remove report --target TARGET`                                     |
| `marimo-studio check TARGET --view report --runtime`                           | `marimo-studio validate report --target TARGET --level runtime`                        |
| `marimo-studio analyze TARGET --view report --server URL`                      | `marimo-studio validate report --target TARGET --level browser --server URL`           |
| `marimo-studio export TARGET --view report --output dist/report`               | `marimo-studio view export report --target TARGET --output dist/report --runtime wasm` |
| `--format json --diagnostics jsonl`                                            | `--json`                                                                               |
| Functions in `marimo_studio.agents`                                            | `marimo_studio.agent.current_workspace()` and its `Workspace` or `View` methods        |
| Saved-workspace helpers in `marimo_studio.workspace`, `checks`, and `export`   | `marimo_studio.authoring.open_workspace()` and its `Workspace` or `View` methods       |
| `CellConfigSpec`, `CellRef`, `CellSpec`, and `SourceSpan` from `marimo_studio` | Import these provider-facing records from `marimo_studio.view_providers`               |

Notebook-local `[tool.marimo-studio]` configuration and project
`pyproject.toml` configuration are mutually exclusive for one notebook. Keep
one configuration source before running the upgraded commands.

After updating the workspace, run:

```console
marimo-studio status --target analysis.py
marimo-studio validate --target analysis.py --level runtime
```

Runtime validation executes the complete notebook with the current user's
filesystem, environment, and network authority. Run it for trusted notebooks.

## Supported environment

| Component                        | 0.1.1 contract                                                                    |
| -------------------------------- | --------------------------------------------------------------------------------- |
| Python                           | 3.10 through 3.14                                                                 |
| Marimo                           | 0.24.0                                                                            |
| [Deno](https://docs.deno.com/)   | 2.9.5 from the `deno` extra for React, Reveal.js, and Svelte authoring            |
| [uv](https://docs.astral.sh/uv/) | Required when the CLI must prepare or re-enter a notebook or provider environment |
| Browser acceptance               | Current Chromium on Linux and Windows                                             |

Server execution can use the packages, files, databases, and credentials
available to its Python environment. Browser execution requires
[Pyodide](https://pyodide.org/)-compatible packages and data sources the visitor
can reach. [Run or export a view](../guide/run-and-share.md) defines those
runtime and delivery boundaries.

## Runtime and delivery matrix

| Delivery             | Python `server` | Browser `wasm` | Prepared `zero-python` |
| -------------------- | --------------- | -------------- | ---------------------- |
| Studio Preview       | Supported       | Supported      | Supported in edit mode |
| Live run-mode server | Supported       | Supported      | Not applicable         |
| Static export        | Not applicable  | Supported      | Default                |

Static exports are HTTP directories. A Prepared export contains the production
artifact, runtime configuration, notebook public files, and precomputed
projection results. A Browser export also contains saved notebook source and
runs it through Pyodide. Imported packages, remote data, fonts, maps, and other
browser resources retain their own network and cross-origin requirements.

## Deployment boundary

`create_asgi_app()` and `marimo_studio.asgi:app` return a run-mode Marimo
[ASGI](https://asgi.readthedocs.io/en/latest/) application with Studio
middleware and owned lifespan cleanup. ASGI is the standard interface between
asynchronous Python web applications and servers. The hosting stack owns
[TLS](https://developer.mozilla.org/en-US/docs/Glossary/TLS) connection
encryption, proxy headers, process supervision, resource limits, and network
exposure. Forward the application lifespan so Studio can close notebook
sessions and background tasks during shutdown.

Marimo authentication supplies `read` and `edit` scopes to Studio routes.
Source mutations also require the Marimo server token. Run-mode presentations
use read access. Keep authentication enabled when a deployment can execute
Python code or reach private files, services, or credentials.

Provider-authored pages run inside a sandboxed
[iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe),
an embedded browser document, with an opaque origin. The sandbox permits
scripts, forms, downloads, modals, pointer lock, and popups. It withholds
same-origin access and top-level navigation. Studio validates navigation,
query, replay, readiness, and observation messages at the parent boundary.

## Third-party view providers

Studio 0.1 requires provider API version `1`. Set
`ProviderInfo.api_version=PROVIDER_API_VERSION` and declare `marimo-studio`
as a dependency. Test the provider against each Studio minor release it supports.

The [View provider API](provider-api.md) defines process execution,
permissions, cancellation, build inputs, output validation, and conformance
limits. Provider packages and their child commands run with the current user's
filesystem, environment, and network authority.

## Support and security

Security fixes target the latest published release and the `main` branch. Use
the latest Studio release when reporting a bug.

- Open public bug reports and support requests in [GitHub
  Issues](https://github.com/marimo-team/marimo-studio/issues).
- Follow the [troubleshooting guide](../guide/troubleshooting.md) to collect
  redacted diagnostic output.
- Report suspected vulnerabilities through the private path in the [security
  policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
