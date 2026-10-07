#!/usr/bin/env bash
set -euo pipefail

error() {
	printf 'ERROR: %s\n' "$1" >&2
}

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
	error "Usage: $0 <40-character-commit-sha>"
	exit 2
fi

commit="$1"

# Count from the release before this commit. The commit keeps its preview
# version after it is tagged as the next release.
if ! base="$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' "$commit^" 2>/dev/null)"; then
	error "No vX.Y.Z release tag precedes $commit. Fetch tags and full history, then retry."
	exit 1
fi
if [[ ! "$base" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
	error "Release tag $base must use final-version form vX.Y.Z"
	exit 1
fi
major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
patch="${BASH_REMATCH[3]}"
count="$(git rev-list --count "$base..$commit")"

printf '%s.%s.%s.dev%s\n' "$major" "$minor" "$((patch + 1))" "$count"
