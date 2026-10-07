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
# version after it is tagged as the next release. Tag globs also match
# suffixed tags such as v0.2.4-rc1, so select final versions by regex.
tags="$(git tag --merged "$commit^" --list 'v*' --sort=-v:refname)"
if ! base="$(grep -m 1 -E '^v[0-9]+\.[0-9]+\.[0-9]+$' <<<"$tags")"; then
	error "No vX.Y.Z release tag precedes $commit. Fetch tags and full history, then retry."
	exit 1
fi
[[ "$base" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]
major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
patch="${BASH_REMATCH[3]}"
count="$(git rev-list --count "$base..$commit")"

printf '%s.%s.%s.dev%s\n' "$major" "$minor" "$((patch + 1))" "$count"
