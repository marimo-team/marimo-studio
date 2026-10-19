#!/usr/bin/env bash
# Serve one notebook in the Studio editor on the port that Portless assigns.
# `make serve` runs this through `portless run`, which sets PORT and routes a
# named .localhost URL to it, so concurrent servers never compete for a port.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: PORT=<port> scripts/serve-notebook.sh NOTEBOOK [MARIMO_EDIT_ARGS...]" >&2
    exit 2
fi
: "${PORT:?Run through make serve, which receives PORT from Portless}"

notebook=$1
shift
exec "${PIXI:-pixi}" run --locked "${UV:-uv}" run --frozen marimo edit "$notebook" \
    --headless --no-token --host 127.0.0.1 --port "$PORT" "$@"
