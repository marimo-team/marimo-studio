---
title: Compatibility and support
description: Supported Python, Marimo, Deno, browser, release, and provider contracts for Marimo Studio 0.1.
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

| Component          | 0.1.0 contract                                   |
| ------------------ | ------------------------------------------------ |
| Python             | 3.10 through 3.14                                |
| Marimo             | 0.24.0                                           |
| Deno               | 2.9.5 for React, Reveal.js, and Svelte authoring |
| Browser acceptance | Current Chromium on Linux and Windows            |

Server execution can use the packages, files, databases, and credentials
available to its Python environment. Browser execution requires Pyodide
compatible packages and data sources the visitor can reach. [Run or publish a
view](../guide/run-and-share.md) defines those runtime and delivery boundaries.

## Third-party view providers

Studio 0.1 requires provider API version `1`. Set
`ProviderInfo.api_version=PROVIDER_API_VERSION` and give a provider package a
bounded Studio dependency such as `marimo-studio>=0.1,<0.2`. Test the provider
before expanding that range to a newer Studio minor release.

The [view provider reference](provider-api.md) defines process execution,
permissions, cancellation, build inputs, and output validation.

## Support and security

Security fixes target the latest published release and the `main` branch. Use
the latest Studio release when reporting a bug.

- Open public bug reports and support requests in [GitHub
  Issues](https://github.com/marimo-team/marimo-studio/issues).
- Follow the [troubleshooting guide](../guide/troubleshooting.md) to collect
  redacted diagnostic output.
- Report suspected vulnerabilities through the private path in the [security
  policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
