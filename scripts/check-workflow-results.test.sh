#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
checker="$script_directory/check-workflow-results.sh"

expect_failure() {
    if "$checker" "$@" >/dev/null 2>&1; then
        echo "Expected workflow result validation to fail: $*" >&2
        exit 1
    fi
}

"$checker" changes true success quality true success browser false skipped
expect_failure quality true skipped
expect_failure browser false success
expect_failure changes true failure
expect_failure changes true cancelled
expect_failure changes maybe success
expect_failure changes true
