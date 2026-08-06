# Releasing

An annotated `vX.Y.Z` tag on `main` starts the PyPI publication workflow. The
tag version must match `packages/marimo-studio/pyproject.toml`.

## Prepare the release pull request

Update the package version on a branch from current `main`:

```console
uv version --package marimo-studio --bump patch
```

Use `minor`, `major`, or an explicit final version when that matches the
release. Commit the package manifest and `uv.lock`. Commit `pnpm-lock.yaml`
when JavaScript dependency inputs also changed.

Run the local release gates before opening the pull request:

```console
make install
make check
make e2e
make package
```

`make package` builds the browser assets, wheel, and source distribution. It
checks both wheels, their entry points, packaged browser files, worker chunks,
and `marimo-studio --version` in isolated environments.

Merge the release pull request after the **CI** and **Browser acceptance**
workflows pass on the release commit.

## Verify the release commit

Update local `main`, then run the release preflight:

```console
git pull --ff-only origin main
./scripts/release.sh --dry-run
```

The script requires:

- A clean local `main` that matches `origin/main`.
- A final `X.Y.Z` package version.
- An absent `vX.Y.Z` tag.
- A successful push-triggered **CI** run for the current commit.

The dry run prints the tag, commit, and CI URL. Confirm that the separate
**Browser acceptance** workflow also passed for the same commit.

## Start publication

Create and push the annotated tag:

```console
./scripts/release.sh
```

Pushing the tag starts `.github/workflows/publish.yml`. The script deletes the
local tag when the push fails, so the same command can retry after the remote
problem is resolved.

The workflow proceeds in this order:

| Job             | Responsibility                                                        |
| --------------- | --------------------------------------------------------------------- |
| `build`         | Validate tag form, version, ancestry, and distribution contents       |
| `publish`       | Publish wheel and source distribution with PyPI Trusted Publishing    |
| `verify-pypi`   | Install the exact public version from PyPI and inspect runtime assets |
| `release-notes` | Create the GitHub release and changelog after public verification     |

The repository's `pypi` environment must be configured as a
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/).

## Recover a failed publication

Inspect the first failed workflow job before retrying. A workflow rerun is
appropriate when infrastructure or PyPI availability caused the failure and
the package version was not published.

PyPI versions are immutable. When `publish` completed, keep the released
artifact and prepare a new patch version for any code or package-content fix.
Wait for `verify-pypi` and `release-notes` to complete before announcing the
release.
