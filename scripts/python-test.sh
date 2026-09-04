#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./scripts/python-test.sh [--profile PROFILE] [--python VERSION] [--parallel] [-- PYTEST_ARGS...]

Run a repository-owned Python test profile.

Profiles:
  all               Run every test in the current development environment.
  standard          Run tests that do not require native processes or Deno.
  supported-python  Run contracts promised across supported Python versions.
  native            Run native process ownership contracts.
  deno              Run Deno provider contracts with the test-deno group.

Options:
  --profile PROFILE  Select a profile. Default: all
  --python VERSION   Use a frozen, isolated environment for VERSION.
  --parallel         Distribute tests across up to eight workers.
  -h, --help         Show this help.

Everything after -- is forwarded to pytest. Unrecognized arguments are also
forwarded, so focused paths and pytest flags work without --.

Examples:
  ./scripts/python-test.sh --profile all
  ./scripts/python-test.sh --profile all --parallel
  ./scripts/python-test.sh --profile standard -x
  ./scripts/python-test.sh --profile supported-python --python 3.13
  ./scripts/python-test.sh --profile native -- packages/marimo-studio/tests/server/test_session_startup.py
EOF
}

profile="all"
python_version=""
parallel=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            if [[ $# -lt 2 ]]; then
                echo "python-test: --profile requires a value" >&2
                exit 2
            fi
            profile="$2"
            shift 2
            ;;
        --python)
            if [[ $# -lt 2 ]]; then
                echo "python-test: --python requires a version" >&2
                exit 2
            fi
            python_version="$2"
            shift 2
            ;;
        --parallel)
            parallel=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

group="test"
pytest_args=(pytest)
if [[ "$parallel" == "true" ]]; then
    distribution="worksteal"
    if [[ "$profile" == "all" || "$profile" == "native" ]]; then
        distribution="loadgroup"
    fi
    pytest_args+=(-n auto --maxprocesses=8 --dist "$distribution")
fi
case "$profile" in
    all)
        ;;
    standard)
        pytest_args+=(-m "not native_process and not deno")
        ;;
    supported-python)
        pytest_args+=(-m supported_python)
        ;;
    native)
        pytest_args+=(-m native_process)
        ;;
    deno)
        group="test-deno"
        pytest_args+=(-m deno)
        ;;
    *)
        echo "python-test: unknown profile '$profile'" >&2
        echo "Choose all, standard, supported-python, native, or deno." >&2
        exit 2
        ;;
esac

uv_args=(run)
if [[ -n "$python_version" ]]; then
    uv_args+=(
        --frozen
        --isolated
        --no-dev
        --group "$group"
        --python "$python_version"
    )
elif [[ "$group" != "test" ]]; then
    uv_args+=(--group "$group")
fi

if [[ "$profile" == "deno" ]]; then
    uv "${uv_args[@]}" python -c \
        "from marimo_studio.view_providers._bundled import _deno; assert _deno.deno_availability().available"
fi

exec uv "${uv_args[@]}" "${pytest_args[@]}" "$@"
