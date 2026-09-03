# Contributing

Marimo Studio accepts focused changes that preserve the notebook, view,
artifact, projection, and runtime ownership boundaries.

## Before you start

- Read [README.md](README.md) for the product model.
- Read the [contributor guide](development_docs/README.md) and [architecture
  map](development_docs/architecture.md) before changing lifecycle or ownership.
- Report suspected vulnerabilities through [SECURITY.md](SECURITY.md).

## Set up

The repository uses Python, `uv`, Node.js, pnpm, Deno, and Chromium. Their
supported versions are declared in `pyproject.toml`, `package.json`, and the
lockfiles.

```console
make setup
```

Use focused package tests while working. Run the repository gates before asking
for review:

```console
make check
make build
make e2e
make package
```

For public documentation changes, also run:

```console
make docs-build
```

## Keep changes inside the owning boundary

- Marimo integration belongs in `marimo_studio._compat` and
  `packages/marimo-frontend`.
- View providers describe source and build browser files. Core owns validation,
  publication, projection authorization, and workspace state.
- Browser records belong in `packages/protocol`.
- Public behavior needs a contract test through the Python API, CLI, file,
  protocol, package, or browser boundary that users depend on.

Read [Frontend development](development_docs/frontend.md) for browser changes and
[Release workflow](development_docs/releasing.md) for distribution changes.

## Pull requests

- Keep the diff tied to one product or ownership goal.
- Include tests for supported behavior and distinct failure boundaries.
- Update public docs when commands, configuration, APIs, or user workflows
  change.
- List skipped validation commands and the reason.
- Let repository formatters and checks own mechanical output.

First-time contributors may be asked to sign the [marimo contributor license
agreement](https://marimo.io/cla).
