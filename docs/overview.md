---
title: How Studio works
description: How one reactive notebook supplies several custom web views.
---

# How Studio works

Marimo Studio separates analytical ownership from presentation ownership.

| Notebook owns                        | View owns                        |
| ------------------------------------ | -------------------------------- |
| Data access and transformations      | Page structure and copy          |
| Metrics and domain decisions         | Styles and browser interactions  |
| Controls and reactive dependencies   | Frontend source and build config |
| Python packages, files, and services | Published browser files          |

Several views can reuse one notebook graph without copying its analytical
logic.

## View project

The smallest view has two authored files:

```text
dashboard/
  view.toml
  index.html
  .artifacts/  generated
```

`view.toml` selects an installed frontend extension:

```toml
schema = 1
provider = "marimo-studio/vanilla"
```

The extension reports source documents and build inputs. It can use any
frontend source tree or build tool. Studio owns the manifest, generated
artifact store, and publication rules.

## Notebook results

Frontend source declares where notebook results belong:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Studio resolves each target to the current notebook producer and dependency
closure. Marimo renders rich outputs and owns control updates.

## Publication

A build follows one path:

```text
saved source
  -> immutable input snapshot
  -> frontend build
  -> candidate validation
  -> atomic publication
  -> presentation
```

The current page changes only after the complete candidate passes validation.
A failed build retains the previous publication.

Generated state lives under `.artifacts/` and stays ignored. It can be rebuilt
from the authored view directory.

## Live authoring

The Studio workspace combines:

- **Notebook** for analytical code
- **Develop** for notebook, source, and preview together
- **Preview** for the selected audience view
- **Source** for frontend documents

View changes use one selection transaction. Pending source is flushed before
the selected view, preview, route, and source session commit. A newer selection
supersedes older work.

Several browser windows share source publication work while retaining separate
sessions, selections, and unsaved buffers.

## Delivery

The same published browser files support:

- a Python-backed server runtime
- a compatible notebook running in a browser worker
- static export

Choose the runtime according to the notebook's data and dependency boundary.

[Getting started](guide/getting-started.md) creates the first view.
[Contributor architecture](https://github.com/marimo-team/marimo-studio/blob/main/development_docs/architecture.md)
maps implementation ownership.
