# Releasing Marimo Studio

An annotated `vX.Y.Z` tag on `main` starts the trusted PyPI publication
workflow. The tag version must match
`packages/marimo-studio/pyproject.toml`.

## Release unit

A release contains one coordinated compatibility unit:

- `marimo-studio` Python package and CLI
- Marimo server middleware, kernel lifespan, and agent capability entry points
- `marimo_studio.view_provider` entry points
- Vanilla, React, and Svelte provider implementations
- Provider analyzers and project starters
- Provider guides and the Marimo Studio Agent Plugin
- Optional Deno dependency metadata
- Generated Studio, presentation, runtime, and WebAssembly browser assets
- Supported Marimo version, tag commit, and private layout fingerprints
- Wheel and source distribution metadata needed to rebuild the same wheel

Provider info, packaged starters, module help, CLI catalogs, browser
assets, and public docs should describe the same release.

## Dependency identity

Define release-affecting version policy in its owning manifest or lockfile:

- uv range from `[tool.uv].required-version` in the root `pyproject.toml`
- Marimo Python requirement
- Deno Python distribution and executable
- React and React DOM template imports
- Svelte compiler
- Official Svelte Vite plugin
- Vite, TypeScript, and source analyzers
- Starter lockfiles

Review dependency and lockfile changes before adding them. Run `pip-audit`
after a Python dependency change. Respect the machine package-age policy and
stop when an age gate rejects a release.

## Prepare the release pull request

Start from current `main`, then update the package version:

```console
uv version --package marimo-studio --bump patch
```

Use `minor`, `major`, or an explicit final version when that matches the
release. Commit the package manifest and `uv.lock`. Commit `pnpm-lock.yaml`
when JavaScript dependency inputs changed. Commit view-project lockfiles when a
packaged starter changes its frontend dependencies.

Run the release gates from the repository root:

```console
make setup
make check
make e2e
make docs-build
make package
```

The gates provide different evidence:

| Gate              | Release contract                                                                                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `make check`      | Formatting, static analysis, package tests, frontend tests, provider checks, and `examples/nga.py` pass                               |
| `make e2e`        | Provider builds, native editor, Source, artifact preview, kernel, worker, dynamic projections, and view switching compose in Chromium |
| `make docs-build` | Public navigation, examples, and reference pages build                                                                                |
| `make package`    | Browser assets, distributions, provider entry points, starters, optional extras, and installed commands verify                        |

Merge after CI, Browser acceptance, and documentation workflows pass on the
release commit.

## Validate packaged providers

`make package` builds the wheel, source distribution, and source-rebuilt wheel
before checking metadata on all three. `scripts/verify-dist.sh` requires the
two wheels to be byte-identical, then runs the installed-package matrix once.

The base installation verifies:

- Package version and import
- Public import allowlist and `py.typed`
- Runtime and Studio browser assets
- Provider, agent, and CLI entry points
- Agent Plugin discovery through `agent_plugins.locate()`
- Starter discovery and the default vanilla starter
- Vanilla view creation, publication, and static validation
- Separately packaged provider creation, build, and type checking
- Packaged Agent Plugin resources in both distributions
- Absence of the optional Deno runtime from the base installation

The package gate also enforces these release budgets:

| Artifact                         |  Budget |
| -------------------------------- | ------: |
| Wheel or source distribution     |   8 MiB |
| Browser asset files              |     400 |
| Browser asset bytes              |  24 MiB |
| Direct runtime and Studio assets | 600 KiB |
| Gzipped direct assets            | 120 KiB |

`scripts/verify-pypi.sh` polls for the exact package version with a minimal
probe. After the version appears, it runs the complete base check and Deno
check once. The Deno check creates and builds the React and Svelte starters
with the published package.

Both scripts use isolated, uncached environments while retaining the
repository dependency-age policy.

## Validate the repository example

`examples/nga.py` is the release example. Its `overview`, `gallery`, and
`story` views exercise vanilla, React, and Svelte through one notebook graph.
Overview is the single-document Vanilla baseline. Its CSS and JavaScript are
inline in `index.html`.

Release validation should:

1. Run Marimo notebook checks.
2. Inspect every view project.
3. Build development and production artifacts for each provider.
4. Run static and isolated runtime checks.
5. Exercise Server and WebAssembly previews.
6. Validate dynamic React and Svelte targets.
7. Confirm Source tabs at desktop and narrow widths.

`scripts/verify-example-artifacts.py` copies the example to a temporary
directory, builds development and production output for every view, and checks
the resulting files through the artifact API. The source tree contains no
generated `.artifacts/` state.

## Validate the pinned Marimo release

Treat a Marimo upgrade as an integration change before a version bump. Follow
[Marimo integration](architecture/marimo-integration.md) to update:

- Exact Python pin
- `_compat/release.json`
- Private Python adapters
- Prepared frontend source
- Browser build metadata
- Server and WebAssembly acceptance
- Package verification

The release manifest, installed Marimo distribution, prepared frontend commit,
and generated browser assets must identify the same release.

## Verify the exact release commit

Update local `main`, then run the preflight:

```console
git pull --ff-only origin main
./scripts/release.sh --dry-run
```

The preflight validates:

1. The current branch is `main`.
2. The working tree is clean.
3. Local `main` matches `origin/main` after fetching branches and tags.
4. The package version has final `X.Y.Z` form.
5. The corresponding `vX.Y.Z` tag is available.
6. Push-triggered CI, Browser acceptance, and documentation passed for the
   exact commit.

The command prints the release tag, commit, and all three workflow URLs. The
publish workflow repeats the exact-commit check before building artifacts.

## Start publication

Create and push the annotated tag:

```console
./scripts/release.sh
```

The tag starts `.github/workflows/publish.yml`.

```mermaid
flowchart LR
    Tag[Annotated version tag] --> Build[Build and inspect distributions]
    Build --> Publish[Trusted publish to PyPI]
    Publish --> Verify[Fresh base and Deno-extra installs]
    Verify --> Notes[GitHub release notes]
```

| Job             | Responsibility                                                     | Evidence                                                 |
| --------------- | ------------------------------------------------------------------ | -------------------------------------------------------- |
| `build`         | Validate tag, package version, ancestry, and distribution contents | Wheel and source distribution artifact                   |
| `publish`       | Publish both artifacts through PyPI Trusted Publishing             | Immutable public package version                         |
| `verify-pypi`   | Install the exact base package and Deno extra                      | Imports, providers, starters, builds, and assets succeed |
| `release-notes` | Generate the GitHub release after public verification              | Release page tied to the published tag                   |

The repository `pypi` environment must be configured as a
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/).

## Verify the public package

Public verification should use the real PyPI index and a fresh isolated
environment. Check the base package first, then the Deno extra.

Representative commands:

```console
uvx marimo-studio --version
uvx marimo-studio doctor --json
uvx marimo-studio starters --json
```

Use an isolated `uv run --with "marimo-studio[deno]==X.Y.Z"` environment for
React and Svelte availability and build checks. Replace `X.Y.Z` with the
release version being verified.

The public workflow should create a temporary notebook and views, build their
artifacts, inspect the provider catalog, and confirm packaged runtime assets.

## Recover a failed publication

Inspect the first failed job and preserve evidence from that boundary.

| First failed job                           | Response                                                                                                                           |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `build`                                    | Correct source or packaging inputs, bump the version when needed, and publish from a new validated commit                          |
| `publish` before PyPI accepted the version | Resolve the trusted-publishing or service problem, then rerun the workflow                                                         |
| `verify-pypi`                              | Inspect the installed provider, starter, extra, or asset failure and prepare a patch release when the public artifact is defective |
| `release-notes`                            | Rerun after public package verification succeeds                                                                                   |

PyPI versions are immutable. After publication, preserve that artifact and
prepare a new patch version for a code or package-content correction.

If the tag push fails, `scripts/release.sh` deletes the local tag. Fix the
remote problem and run the command again from the same validated commit.
