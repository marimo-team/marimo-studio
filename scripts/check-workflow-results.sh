#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 || $# % 3 != 0 )); then
    echo "Usage: check-workflow-results.sh NAME REQUIRED RESULT [...]" >&2
    exit 2
fi

while (( $# > 0 )); do
    name="$1"
    required="$2"
    result="$3"
    shift 3

    case "$required" in
        true)
            expected="success"
            ;;
        false)
            expected="skipped"
            ;;
        *)
            echo "Invalid required state for $name: $required" >&2
            exit 2
            ;;
    esac
    if [[ "$result" != "$expected" ]]; then
        echo "$name returned $result, expected $expected" >&2
        exit 1
    fi
done
