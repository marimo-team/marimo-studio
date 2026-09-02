#!/usr/bin/env bash
set -euo pipefail

error() {
	printf 'ERROR: %s\n' "$1" >&2
}

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
	error "Usage: $0 <40-character-commit-sha>"
	exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
	error "Missing required command: gh"
	exit 1
fi

commit="$1"
checks=(
	"CI|ci.yml"
	"Browser acceptance|e2e.yml"
	"Documentation|pages.yml"
)

for check in "${checks[@]}"; do
	IFS='|' read -r label workflow <<<"$check"
	run="$(gh run list \
		--workflow "$workflow" \
		--branch main \
		--commit "$commit" \
		--event push \
		--limit 1 \
		--json databaseId,status,conclusion,url \
		--jq 'if length == 0 then "" else (.[0] | [.databaseId, .status, .conclusion, .url] | .[]) end')"
	if [[ -z "$run" ]]; then
		error "No $label run found for $commit"
		exit 1
	fi
	{
		IFS= read -r run_id
		IFS= read -r status
		IFS= read -r conclusion
		IFS= read -r url
	} <<<"$run"
	conclusion="${conclusion:-pending}"
	if [[ "$status" != "completed" || "$conclusion" != "success" ]]; then
		error "$label must pass for $commit. Current result: $status/$conclusion"
		printf 'Run: %s\n' "$url" >&2
		printf 'Watch with: gh run watch %s --exit-status\n' "$run_id" >&2
		exit 1
	fi
	printf '%s: %s\n' "$label" "$url"
done
