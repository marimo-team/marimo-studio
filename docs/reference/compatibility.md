---
title: Compatibility and support
description: Supported Python, Marimo, Deno, uv, browser, runtime, release, provider, deployment, and security contracts for Marimo Studio 0.1.
---

# Compatibility and support

Marimo Studio 0.1.0 is the first public release. The notebook-to-view workflow,
projection elements, and last-successful build behavior are supported product
contracts. Before 1.0, CLI, Python, provider, and saved configuration contracts
may change between minor releases.

Pin Studio and third-party view providers in saved notebooks and deployed
projects:

```toml
dependencies = ["marimo-studio==0.1.0"]
```

## Supported environment

| Component                        | 0.1.0 contract                                                                    |
| -------------------------------- | --------------------------------------------------------------------------------- |
| Python                           | 3.10 through 3.14                                                                 |
| Marimo                           | 0.24.0                                                                            |
| [Deno](https://docs.deno.com/)   | 2.9.5 from the `deno` extra for React, Reveal.js, and Svelte authoring            |
| [uv](https://docs.astral.sh/uv/) | Required when the CLI must prepare or re-enter a notebook or provider environment |
| Browser acceptance               | Current Chromium on Linux and Windows                                             |

Server execution can use the packages, files, databases, and credentials
available to its Python environment. Browser execution requires
[Pyodide](https://pyodide.org/)-compatible packages and data sources the visitor
can reach. [Run or publish a view](../guide/run-and-share.md) defines those
runtime and delivery boundaries.

## Runtime and delivery matrix

| Delivery             | Python runtime | Browser runtime |
| -------------------- | -------------- | --------------- |
| Studio Preview       | Supported      | Supported       |
| Live run-mode server | Supported      | Supported       |
| Static export        | Not applicable | Supported       |

Static exports are HTTP directories. They contain the saved notebook source,
production artifact, Browser runtime, runtime configuration, and notebook
public files. Imported packages, remote data, fonts, maps, and other browser
resources retain their own network and cross-origin requirements.

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
`ProviderInfo.api_version=PROVIDER_API_VERSION` and give a provider package a
bounded Studio dependency such as `marimo-studio>=0.1,<0.2`. Test the provider
before expanding that range to a newer Studio minor release.

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
