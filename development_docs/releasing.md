# Releasing

Releases use annotated `vX.Y.Z` tags from a clean `main` branch with passing CI.

## Prepare

Update the package version:

```console
uv version --bump patch
```

Commit `pyproject.toml` and `uv.lock`, merge the change, and wait for CI on
`main`.

## Verify and tag

Check the release state:

```console
./scripts/release.sh --dry-run
```

Create and push the tag:

```console
./scripts/release.sh
```

The publish workflow builds the wheel and source distribution, publishes
through PyPI Trusted Publishing, verifies a fresh public installation, and
generates GitHub release notes.

The repository's `pypi` environment must be configured as a
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/).
