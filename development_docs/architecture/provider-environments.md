# Provider environments

The CLI re-enters through [uv](https://docs.astral.sh/uv/)'s `uv run` command
when the target notebook or configured view providers require another Python
environment. Requirement selection happens from durable notebook and project
metadata before any provider is imported.

See [View providers and artifacts](view-providers-and-artifacts.md) for the
provider protocol and publication lifecycle.

## Decision

The saved notebook and containing Python project own provider dependencies.
The invoking Studio process supplies the current Studio version as a bootstrap
default. Target metadata can select an exact version, compatible range, direct
URL, or uv source under the constraints defined in this page.

Provider discovery never installs a missing package. A command that needs a
provider resolves the target environment, starts a child CLI there, then loads
the provider entry point in that child.

## Environment target

`environment_root()` selects the nearest notebook ancestor containing
`pyproject.toml`. A Python project is active when that file contains `[project]`
or `[tool.uv.workspace]`. Otherwise the notebook's
[PEP 723](https://peps.python.org/pep-0723/) inline metadata owns Python and
dependency selection.

View creation preserves project-managed execution. For a project notebook with
no inline dependency list, Studio adds its view configuration without inventing
a sandbox dependency list. The emitted editor command uses `uv run --project`
and `--no-sandbox`, retaining project dependencies and sources. Existing inline
dependencies, sources, indexes, and Python constraints are composed through
the same environment builder used for CLI re-entry. Its returned arguments
are self-contained, so the emitted command remains valid after creation exits. Standalone notebooks receive sandbox requirements.

Notebook execution re-enters the complete target environment when any condition
holds:

- The target has a Python project or uv workspace.
- The notebook declares PEP 723 dependencies.
- The notebook requires another Python version.

Status, view, and static-validation commands use a narrower provider bootstrap
check. They re-enter when a configured provider requirement or declared source
is not satisfied by the current process.

The bootstrap marker prevents recursive re-entry. `--sandbox` and the command's
explicit environment options still decide whether a command may opt in or out
where that surface exposes the choice.

## Requirement composition

Provider keys use `distribution/entry-point` form. Studio derives the owning
distribution from that key without importing it.

Bundled providers map to these launch requirements:

| Provider                | Bootstrap requirement |
| ----------------------- | --------------------- |
| `marimo-studio/vanilla` | `marimo-studio`       |
| `marimo-studio/react`   | `marimo-studio[deno]` |
| `marimo-studio/svelte`  | `marimo-studio[deno]` |

An external provider must appear in PEP 723 or project dependencies. Missing
metadata raises `dependency-error` with the distribution name.

Studio combines requirements in this order:

1. Start with the invoking `marimo-studio==<version>` requirement.
2. Add extras required by bundled providers.
3. Collect the target's active requirement for every external provider.
4. Apply [PEP 508](https://peps.python.org/pep-0508/) environment markers,
   which condition dependencies on Python or platform properties.
5. Resolve a direct URL, exact pin, active uv source, compatible range, or
   bootstrap default.
6. Reject conflicts before constructing the `uv run` command.

A distribution cannot combine an active direct URL with an active uv source or
version range. Multiple active uv sources are invalid. Conflicting exact pins
are invalid. Several active ranges must agree on one selected requirement.

When provider markers depend on a Python version that differs from the current
interpreter, Studio asks the contributor to align the environment first. It
does not guess the marker result for another interpreter.

## Checkout and lock behavior

For a declared Python project, the child command uses `uv run --project` and
adds `--frozen` when `uv.lock` exists. Project-owned sources take precedence
according to uv metadata. Studio adds `--no-sources-package` when project
metadata owns a source that is inactive for the selected requirement.

An editable Studio checkout is injected with `--with-editable` when target
constraints permit the invoking version and do not select another direct or uv
source. An exact target pin to another version keeps that declared version.

The current process removes `VIRTUAL_ENV` before re-entry so uv selects the
target rather than inheriting an unrelated active environment.

## Child CLI protocol

The parent starts:

```text
uv run [target and requirement flags] -- marimo-studio <arguments>
```

Human commands inherit command output. Machine commands use private temporary
result and diagnostic channels:

- The result channel contains the trusted JSON result document.
- The diagnostic channel contains schema 1
  [JSON Lines](https://jsonlines.org/) diagnostic events, one JSON object per
  line.
- Child stdout and stderr from extensions remain bounded untrusted process
  output.

The parent trusts a diagnostic event only when its schema, event type,
severity, code, message, and command match the requested command. Other output
becomes a bounded `process-output` warning.

## Provider execution

The registry loads bundled providers in process. Installed third-party
providers run each `availability`, `starters`, `create`, `inspect`, and `build`
operation in an owned worker process.

The host supplies detached JSON-compatible records and validates the returned
records through provider conformance. It bounds input, output, aggregate
command time, and descendant processes. Host cancellation terminates the worker
process tree. Provider code cannot depend on a cooperative cancellation callback
or a `finally` block running after host cancellation.

Provider subprocess isolation is lifecycle containment. The worker retains the
current user's filesystem, process, environment, and network authority.

## Failure behavior

- Missing `uv` raises `dependency-error` before process creation.
- Invalid metadata or requirement conflicts raise `configuration-error` before
  provider import.
- A child exit with no structured diagnostic produces one bounded
  `process-exit` diagnostic.
- Provider import and conformance failures remain attached to that provider in
  discovery and `doctor` output.
- Timeout, cancellation, malformed output, and descendant cleanup failures
  settle the provider operation before its owner returns.

## Contract tests

- Compose PEP 723 and project dependencies for bundled and external providers.
- Cover markers, extras, exact pins, ranges, direct URLs, uv sources, and
  conflict cases.
- Verify frozen project execution and editable checkout selection.
- Re-enter the CLI and preserve JSON stdout plus JSON Lines stderr.
- Bound untrusted provider output and reject forged child diagnostics.
- Cancel and time out a provider worker with descendants, then verify cleanup.
- Install one external provider package and exercise discovery, creation,
  inspection, build, type checking, and browser mount.
