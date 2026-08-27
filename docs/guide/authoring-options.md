---
title: Frontend authoring
description: Use any frontend source tree and build tool through installed Studio view providers.
---

# Frontend authoring

A Studio view can use any frontend source tree and build tool. The default
starter uses one HTML file with inline styles and scripts. Installed view
providers can create other source trees and invoke existing builders.

List available starting points:

```console
marimo-studio starters
```

Create a view from a selected starter:

```console
marimo-studio view create dashboard \
  --target analysis.py \
  --starter marimo-studio/vanilla:default
```

Starter IDs combine the provider key with a provider-local key. Independent
view providers can use the same local key.

Starter files are written once. After creation, edit them with Studio, an IDE,
or normal filesystem tools.

## Bring a custom toolchain

Install a Python package that registers a
[`marimo_studio.view_provider` entry point](https://packaging.python.org/en/latest/specifications/entry-points/).
An entry point is installed package metadata that maps a group and name to an
importable Python object. Studio discovers that group through
[`importlib.metadata.entry_points()`](https://docs.python.org/3/library/importlib.metadata.html#entry-points)
and loads each registered provider.

The provider reports source documents and build inputs, then writes a browser
candidate into the staging directory supplied by Studio.

The provider may wrap any existing project command that returns a browser
entry document and keeps its output inside staging.

```toml
schema = 1
provider = "acme-views/report"

[options]
entrypoint = "web/report.html"
```

Check an installed view provider:

```console
marimo-studio doctor acme-views/report
```

## Source ownership

Studio owns the manifest and generated control state:

- `view.toml` records the provider and explicit project options.
- Each view's `.artifacts/` stores build staging, provider cache, immutable
  published browser revisions, and development and production receipts. Studio
  can retain the last valid publication when a replacement build fails.
- The workspace `.locks/` directory holds cross-process locks that serialize
  catalog changes, view mutations, builds, and artifact access during view
  replacement.

Studio validates provider output before publication. The view provider owns
authored source and native tool configuration. The workspace `.gitignore`
keeps `.artifacts/` and `.locks/` out of version control. Studio creates them
as needed, and artifact state can be rebuilt from source.

## Build behavior

Each development or production build captures an immutable project snapshot. A
provider can vary optimization by profile. Studio validates and publishes the
result, then keeps the last valid publication if a later build fails.

[View provider API](../reference/provider-api.md) defines the protocol.
[View projects](../reference/view-project.md) defines the filesystem contract.
