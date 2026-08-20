#!/usr/bin/env bash
set -euo pipefail

error() {
	printf 'ERROR: %s\n' "$1" >&2
}

require_env() {
	if [[ -z "${!1:-}" ]]; then
		error "Missing required environment variable: $1"
		exit 1
	fi
}

require_env GITHUB_REF_NAME
require_env GITHUB_REF
require_env GITHUB_SHA
require_env GH_TOKEN

if [[ ! "$GITHUB_REF_NAME" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	error "Release tag must use final-version form vX.Y.Z: $GITHUB_REF_NAME"
	exit 1
fi

package_version="$(uv version --package marimo-studio --short)"
if [[ "v$package_version" != "$GITHUB_REF_NAME" ]]; then
	error "Package version $package_version does not match tag $GITHUB_REF_NAME"
	exit 1
fi

release_notes=".github/release-notes/$GITHUB_REF_NAME.md"
if [[ ! -s "$release_notes" ]]; then
	error "Release notes are missing or empty: $release_notes"
	exit 1
fi

if [[ "$(git cat-file -t "$GITHUB_REF")" != tag ]]; then
	error "Release tag $GITHUB_REF_NAME must be annotated"
	exit 1
fi

release_commit="$(git rev-list -n 1 "$GITHUB_REF")"
if [[ "$release_commit" != "$GITHUB_SHA" ]]; then
	error "Release workflow SHA $GITHUB_SHA does not match tag commit $release_commit"
	exit 1
fi
if ! git merge-base --is-ancestor "$release_commit" origin/main; then
	error "Release commit $release_commit is not on origin/main. Fetch origin/main and tag a merged commit."
	exit 1
fi
./scripts/require-release-checks.sh "$release_commit"
