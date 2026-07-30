#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

shopt -s nullglob
wheels=(
	"$root"/dist/marimo_studio-*.whl
	"$root"/dist/from-sdist/marimo_studio-*.whl
)

if [[ "${#wheels[@]}" -ne 2 ]]; then
	printf 'ERROR: Expected the release wheel and one wheel rebuilt from the source distribution\n' >&2
	exit 1
fi

export UV_NO_CONFIG=1

for wheel in "${wheels[@]}"; do
	uv run --no-project --isolated --no-cache --with "$wheel" python - <<'PY'
from importlib.metadata import distribution
import subprocess

import marimo_studio
from marimo_studio._assets import runtime_assets_path

assert marimo_studio.__name__ == "marimo_studio"
dist = distribution("marimo-studio")
entry_points = {(entry.group, entry.name) for entry in dist.entry_points}
assert ("console_scripts", "marimo-studio") in entry_points
assert ("marimo.server.asgi.middleware", "marimo-studio") in entry_points
assert ("marimo.kernel.lifespan", "marimo-studio") in entry_points

assets = runtime_assets_path()
for filename in (
    "runtime.js",
    "runtime.css",
    "dev-reload.js",
    "studio.js",
    "studio.css",
    "build-meta.json",
):
    assert (assets / filename).is_file(), filename

result = subprocess.run(
    ["marimo-studio", "--version"],
    check=True,
    capture_output=True,
    text=True,
)
assert result.stdout.strip() == f"marimo-studio, version {dist.version}"
PY
done
