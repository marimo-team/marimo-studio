#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist_dir="${1:-$root/dist}"
cd "$root"

if [[ $# -gt 1 ]]; then
	printf 'Usage: ./scripts/verify-installed-wheel.sh [DIST_DIR]\n' >&2
	exit 2
fi

shopt -s nullglob
wheels=("$dist_dir"/marimo_studio-*.whl)
if [[ ${#wheels[@]} -ne 1 ]]; then
	printf 'ERROR: Expected one Marimo Studio wheel in %s\n' "$dist_dir" >&2
	exit 1
fi

wheel="${wheels[0]}"
plugin_digests="$dist_dir/agent-plugin-digests.json"
if [[ ! -f "$plugin_digests" ]]; then
	printf 'ERROR: Missing Agent Plugin digest map: %s\n' "$plugin_digests" >&2
	exit 1
fi

package_version="$(uv run --no-project --isolated python - "$wheel" <<'PY'
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile
import sys

path = Path(sys.argv[1])
with ZipFile(path) as wheel:
    metadata = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
    print(BytesParser().parsebytes(wheel.read(metadata))["Version"])
PY
)"
wheel_uri="$(uv run --no-project --isolated python - "$wheel" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).resolve().as_uri())
PY
)"
bootstrap_root="$(mktemp -d "${TMPDIR:-/tmp}/marimo-studio-bootstrap.XXXXXX")"
trap 'rm -rf "$bootstrap_root"' EXIT
wheelhouse="$bootstrap_root/wheels"
mkdir "$wheelhouse"
uv build --wheel --out-dir "$wheelhouse" \
	"$root/apps/e2e/fixtures-provider/provider"
provider_wheels=("$wheelhouse"/marimo_studio_e2e_provider-*.whl)
if [[ ${#provider_wheels[@]} -ne 1 ]]; then
	printf 'ERROR: Expected one external provider wheel in %s\n' "$wheelhouse" >&2
	exit 1
fi
provider_wheel="${provider_wheels[0]}"

uv run --no-project --isolated --no-cache --exclude-newer-package marimo-export=false \
	--with "$wheel" \
	python scripts/verify-installed-package.py \
	--expected-version "$package_version" \
	--expected-plugin-digests "$plugin_digests"
uv run --no-project --isolated --no-cache --no-sources-package marimo-studio \
	--exclude-newer-package marimo-export=false \
	--with "$wheel" \
	--with "$root/apps/e2e/fixtures-provider/provider" \
	--with "ty==0.0.69" \
	python scripts/verify-external-provider.py --typecheck
uv run --no-project --isolated --no-cache --exclude-newer-package marimo-export=false \
	--with "marimo-studio[deno] @ $wheel_uri" \
	python scripts/verify-installed-package.py \
	--expected-version "$package_version" \
	--expected-plugin-digests "$plugin_digests" \
	--deno

MARIMO_STUDIO_ACCEPTANCE_STUDIO_WHEEL="$wheel" \
	MARIMO_STUDIO_ACCEPTANCE_PROVIDER_WHEEL="$provider_wheel" \
	uv run --no-project --isolated --no-cache --no-sources-package marimo-studio \
		--no-sources-package marimo-studio-e2e-provider \
		--exclude-newer-package marimo-export=false \
		--with "marimo-studio[deno] @ $wheel_uri" \
		--with "$provider_wheel" \
	python scripts/verify-provider-bootstrap.py prepare \
	"$bootstrap_root/workspace"
uv run --no-project --isolated --no-cache --no-sources-package marimo-studio \
	--exclude-newer-package marimo-export=false \
	--with "$wheel" \
	python scripts/verify-provider-bootstrap.py verify \
	"$bootstrap_root/workspace"
