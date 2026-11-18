# Releases

Maintainers request a release with an authenticated GitHub CLI:

```sh
./scripts/release.sh patch
```

Accepts `patch`, `minor`, `major`, or a stable `X.Y.Z` version.
Review and merge the generated PR to approve publication.
See the [maintainer runbook](https://github.com/marimo-team/github-maintenance/blob/main/docs/releases.md) (internal).

Add `.github/release-notes/vX.Y.Z.md` to the PR before merging.
See [package checks and previews](development_docs/releasing.md) for repository-specific details.
