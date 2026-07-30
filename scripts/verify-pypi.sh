#!/usr/bin/env bash
set -euo pipefail

version="${RELEASE_VERSION:-}"
if [[ -z "$version" ]]; then
	ref_name="${GITHUB_REF_NAME:-}"
	version="${ref_name#v}"
fi

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	printf 'ERROR: Release version must use final-version form X.Y.Z: %s\n' "$version" >&2
	exit 1
fi

export UV_NO_CONFIG=1

for ((attempt = 1; attempt <= 18; attempt++)); do
	if RELEASE_VERSION="$version" uv run \
		--no-cache \
		--no-project \
		--isolated \
		--default-index https://pypi.org/simple \
		--with "marimo-studio==$version" \
		python -c "import os; from importlib.metadata import version; import marimo_studio; from marimo_studio._assets import runtime_assets_path; assert version('marimo-studio') == os.environ['RELEASE_VERSION']; p = runtime_assets_path(); assert (p / 'runtime.js').is_file()"; then
		exit 0
	fi

	printf 'PyPI verification attempt %s of 18 did not verify %s\n' "$attempt" "$version"
	if [[ "$attempt" -lt 18 ]]; then
		sleep 10
	fi
done

printf 'ERROR: PyPI did not verify marimo-studio %s within three minutes\n' "$version" >&2
exit 1
