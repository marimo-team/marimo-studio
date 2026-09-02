---
title: Reference
description: Exact commands, configuration, projection, Python, provider, compatibility, limit, identity, and error contracts.
---

# Reference

Use these pages to look up an exact Marimo Studio contract. The [guide](../guide/index.md)
owns task workflows and developed examples.

## Product contracts

| Contract                                                        | Reference                                        |
| --------------------------------------------------------------- | ------------------------------------------------ |
| Commands, output, and exit status                               | [CLI](cli.md)                                    |
| Server entry, notebook settings, view projects, and saved files | [Configuration](configuration.md)                |
| Cells, rendered outputs, live values, and DOM events            | [Notebook result projections](projections.md)    |
| Provider keys, starters, and built-in options                   | [Built-in view providers](built-in-providers.md) |
| Revisions, generations, runtime instances, and state names      | [Identities and state](identities.md)            |
| File, projection, payload, and timeout boundaries               | [Limits](limits.md)                              |
| Machine output and expected failures                            | [Errors and JSON](errors-and-json.md)            |
| Supported releases and execution environments                   | [Compatibility and support](compatibility.md)    |

## Extension contracts

| Contract                                                          | Reference                            |
| ----------------------------------------------------------------- | ------------------------------------ |
| Saved-workspace, code-mode, inspection, and ASGI APIs             | [Python API](python-api.md)          |
| Third-party provider registration, inspection, and build protocol | [View provider API](provider-api.md) |

## Terms

A **view** is one named presentation of a saved notebook. Its **view project**
contains authored frontend source and `view.toml`. A **view provider** inspects
that source and builds an immutable browser **artifact**. Studio combines the
artifact with a notebook runtime to create a **presentation** in Preview or run
mode.

See [Identities and state](identities.md) for the complete term and identity
map.
