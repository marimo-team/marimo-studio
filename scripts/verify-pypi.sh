#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	printf 'Usage: %s X.Y.Z\n' "$0" >&2
	exit 2
fi

version="$1"

probe_version() {
	uv run \
		--no-cache \
		--no-project \
		--isolated \
		--default-index https://pypi.org/simple \
		--with "marimo-studio==$version" \
		python -c "from importlib.metadata import version; assert version('marimo-studio') == '$version'"
}

verify_base() {
	uv run \
		--no-cache \
		--no-project \
		--isolated \
		--default-index https://pypi.org/simple \
		--with "marimo-studio==$version" \
		python scripts/verify-installed-package.py --expected-version "$version"
}

verify_deno() {
	uv run \
		--no-cache \
		--no-project \
		--isolated \
		--default-index https://pypi.org/simple \
		--with "marimo-studio[deno]==$version" \
		python scripts/verify-installed-package.py \
		--expected-version "$version" \
		--deno
}

published=0
for ((attempt = 1; attempt <= 18; attempt++)); do
	if probe_version; then
		published=1
		break
	fi

	printf 'PyPI verification attempt %s of 18 did not verify %s\n' "$attempt" "$version"
	if [[ "$attempt" -lt 18 ]]; then
		sleep 10
	fi
done

if [[ "$published" -ne 1 ]]; then
	printf 'ERROR: PyPI did not publish marimo-studio %s within three minutes\n' "$version" >&2
	exit 1
fi

verify_base
verify_deno
