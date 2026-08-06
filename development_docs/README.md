# Contributor guide

Marimo Studio spans a Python extension, two browser documents, a shared wire
protocol, and a VitePress site. Start from the component that owns the behavior
you are changing, then validate through the boundary its consumers use.

## Start a contribution

Install the locked Python and JavaScript environments:

```console
make install
```

Run focused tests while working. Finish with the repository gate:

```console
make check
```

`make check` checks formatting, linting, types, and tests for the Python and
browser packages. Changes that cross the Python and browser boundary also
require:

```console
make build
make e2e
```

## Choose the owning guide

| Change                                                          | Guide                                  |
| --------------------------------------------------------------- | -------------------------------------- |
| Python boundaries, routes, sessions, runtimes, or static export | [Architecture](architecture.md)        |
| Browser packages, Studio features, view rendering, or Marimo UI | [Frontend workspace](frontend.md)      |
| Version, distribution, tag, PyPI, or release notes              | [Releasing](releasing.md)              |
| Public behavior, examples, configuration, or APIs               | [User documentation](../docs/index.md) |
| Universal repository rules and command lookup                   | [Agent instructions](../AGENTS.md)     |

## Validate at the owning boundary

| Boundary                | Primary check                                                     |
| ----------------------- | ----------------------------------------------------------------- |
| Workspace and Python    | Focused `pytest` target under `packages/marimo-studio/tests/`     |
| Protocol record         | Protocol schema tests plus producer and consumer checks           |
| Runtime interface       | Runtime tests plus the presentation adapter checks                |
| View document           | Presentation tests plus browser acceptance when lifecycle changes |
| Studio workflow         | Studio package tests plus browser acceptance                      |
| Marimo frontend adapter | Adapter tests, `make build`, and CI's Marimo lower-bound job      |
| Static distribution     | Export tests and `make package`                                   |
| Documentation           | `make docs-build` and rendered browser inspection                 |

Tests stay with the package that owns the contract. Put end-to-end coverage in
`apps/e2e` when the behavior crosses the native editor, kernel, filesystem, or
preview documents.

## Keep source and generated output separate

Edit source under `packages/`, `apps/`, `docs/`, and `development_docs/`.
`make build` writes browser assets under
`packages/marimo-studio/src/marimo_studio/_static/`. That directory and the
prepared Marimo source under `packages/marimo-frontend/.cache/` are generated
and remain untracked.
