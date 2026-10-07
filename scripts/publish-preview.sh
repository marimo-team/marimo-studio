#!/usr/bin/env bash
set -euo pipefail

error() {
	printf 'ERROR: %s\n' "$1" >&2
}

if [[ "$#" -ne 2 || ! "$2" =~ ^[0-9a-f]{40}$ ]]; then
	error "Usage: $0 <wheel> <40-character-commit-sha>"
	exit 2
fi
if [[ -z "${GH_REPO:-}" ]]; then
	error "Missing required environment variable: GH_REPO"
	exit 1
fi

wheel="$1"
commit="$2"
name="$(basename "$wheel")"
if [[ ! "$name" =~ ^marimo_studio-([0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]+)-py3-none-any\.whl$ ]]; then
	error "Expected a marimo-studio preview wheel: $name"
	exit 1
fi
version="${BASH_REMATCH[1]}"

tag="preview"
retained=30
server="${GITHUB_SERVER_URL:-https://github.com}"
release_url="$server/$GH_REPO/releases/tag/$tag"
wheel_url="$server/$GH_REPO/releases/download/$tag/$name"

# The tag ruleset keeps tags immutable, so the preview tag stays on the commit
# that created the release. Download URLs depend on the tag name only.
if ! gh release view "$tag" >/dev/null 2>&1; then
	gh release create "$tag" \
		--prerelease \
		--target "$commit" \
		--title "Preview builds" \
		--notes "Wheels built from main."
fi

assets() {
	gh release view "$tag" --json assets --jq '.assets[].name'
}

published="$(assets)"
if grep -qxF "$name" <<<"$published"; then
	printf '%s is already published.\n' "$name"
else
	gh release upload "$tag" "$wheel"
fi

listing="$(assets)"
wheels="$(grep -E '^marimo_studio-.+\.whl$' <<<"$listing" | sort -rV)"

# Completion order can differ from merge order, so only the newest wheel
# rewrites the release notes.
if [[ "$(head -n 1 <<<"$wheels")" == "$name" ]]; then
	notes="$(mktemp)"
	trap 'rm -f "$notes"' EXIT
	cat >"$notes" <<EOF
Wheels built from \`main\` after CI, Browser acceptance, Platform acceptance, and GitHub Pages pass. The newest is marimo-studio \`$version\` from [\`${commit:0:7}\`]($server/$GH_REPO/commit/$commit).

Install it as a tool:

\`\`\`console
uv tool install "marimo-studio @ $wheel_url"
\`\`\`

Or declare it in a notebook's inline script metadata:

\`\`\`python
# /// script
# dependencies = ["marimo-studio @ $wheel_url"]
# ///
\`\`\`

Sandboxed kernels install Studio from the same URL. This release keeps the newest $retained wheels. Install \`marimo-studio\` from PyPI for released versions.

Check that a wheel was built by this repository:

\`\`\`console
gh attestation verify $name -R $GH_REPO
\`\`\`
EOF
	gh release edit "$tag" --notes-file "$notes"
fi

stale="$(tail -n "+$((retained + 1))" <<<"$wheels")"
while IFS= read -r asset; do
	if [[ -n "$asset" ]]; then
		gh release delete-asset "$tag" "$asset" --yes
	fi
done <<<"$stale"

pull="$(gh api "repos/$GH_REPO/commits/$commit/pulls" \
	--jq '[.[] | select(.merged_at != null)][0].number // empty')"
if [[ -n "$pull" ]]; then
	comments="$(gh api --paginate "repos/$GH_REPO/issues/$pull/comments" --jq '.[].body')"
	if ! grep -qF "$wheel_url" <<<"$comments"; then
		gh pr comment "$pull" --body "marimo-studio \`$version\` from this pull request is available as a [preview build]($release_url):

\`\`\`console
uv tool install \"marimo-studio @ $wheel_url\"
\`\`\`"
	fi
fi

printf 'Published %s\n' "$wheel_url"
