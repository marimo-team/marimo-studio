# Releasing

An annotated `vX.Y.Z` tag on `main` starts the PyPI publishing workflow.

## Prepare

Update the package version and run the repository gates:

```console
uv version --package marimo-studio --bump patch
make install
make check
make package
```

Commit `packages/marimo-studio/pyproject.toml` and `uv.lock`. Merge them to
`main` and wait for the CI run on that commit. Regenerate `uv.lock` or
`pnpm-lock.yaml` when the release also changes its corresponding dependency
inputs.

## Tag

Verify the clean, synchronized branch and successful CI:

```console
./scripts/release.sh --dry-run
```

Create and push the annotated tag:

```console
./scripts/release.sh
```

The publish workflow builds the wheel and source distribution, publishes with
PyPI Trusted Publishing, verifies a fresh public installation, and creates the
GitHub release notes.

The repository's `pypi` environment must be configured as a
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/).
