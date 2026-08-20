#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
	cat <<'EOF'
Usage: ./scripts/release.sh [--dry-run]

Releases the package version committed to main. The command requires a clean,
synchronized main branch plus successful CI, Browser acceptance, and
documentation workflows for its current commit. It creates and pushes the
annotated vX.Y.Z tag that starts trusted publishing.

Add the version change to the release pull request with:

  uv version --package marimo-studio --bump patch
EOF
}

error() {
	printf 'ERROR: %s\n' "$1" >&2
}

require_command() {
	if ! command -v "$1" >/dev/null 2>&1; then
		error "Missing required command: $1"
		exit 1
	fi
}

DRY_RUN=0

case "${1:-}" in
"") ;;
--dry-run)
	DRY_RUN=1
	;;
-h | --help)
	usage
	exit 0
	;;
*)
	error "Unknown argument: $1"
	usage >&2
	exit 1
	;;
esac

if [[ "$#" -gt 1 ]]; then
	error "Expected at most one argument"
	usage >&2
	exit 1
fi

require_command gh
require_command git
require_command python3
require_command uv

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
	error "Releases must run from main. Current branch: $BRANCH"
	exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
	error "The working tree must be clean"
	git status --short >&2
	exit 1
fi

git fetch origin main --tags

COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse origin/main)"
if [[ "$COMMIT" != "$REMOTE_COMMIT" ]]; then
	error "Local main must match origin/main"
	printf 'Run git pull --ff-only origin main, then retry.\n' >&2
	exit 1
fi

VERSION="$(uv version --package marimo-studio --short)"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	error "Package version must be a final X.Y.Z version. Current version: $VERSION"
	exit 1
fi

python3 scripts/check-release-dependencies.py --release --public

TAG="v$VERSION"
RELEASE_NOTES=".github/release-notes/$TAG.md"
if [[ ! -s "$RELEASE_NOTES" ]]; then
	error "Release notes are missing or empty: $RELEASE_NOTES"
	exit 1
fi
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
	error "Release tag already exists: $TAG"
	exit 1
fi

CHECKS="$(./scripts/require-release-checks.sh "$COMMIT")"

REPOSITORY_URL="$(gh repo view --json url --jq .url)"

printf 'Release: %s\n' "$TAG"
printf 'Commit:  %s\n' "$COMMIT"
printf '%s\n' "$CHECKS"

if [[ "$DRY_RUN" == "1" ]]; then
	printf '\nDry run complete. Run ./scripts/release.sh to create and push %s.\n' "$TAG"
	exit 0
fi

git tag -a "$TAG" -m "release: $VERSION"
if ! git push origin "$TAG"; then
	git tag -d "$TAG" >/dev/null
	error "Failed to push $TAG. The local tag was deleted so the command can be retried."
	exit 1
fi

printf '\nRelease %s started.\n' "$TAG"
printf 'Publish workflow: %s/actions/workflows/publish.yml\n' "$REPOSITORY_URL"
