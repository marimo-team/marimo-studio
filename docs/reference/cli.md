---
title: CLI reference
description: Inspect notebooks and create, edit, build, validate, activate, export, and remove Studio views.
---

# CLI reference

`marimo-studio` operates on saved notebooks. Pass `--target` a notebook, project
directory, or `pyproject.toml`. When omitted, Studio resolves the current project
configuration.

```text
marimo-studio status [--target PATH]

marimo-studio notebook inspect [--target PATH]
marimo-studio notebook bind ALIAS --cell SELECTOR [--target PATH]

marimo-studio starters

marimo-studio view create VIEW [--target PATH] [--starter ID]
marimo-studio view inspect VIEW [--target PATH]
marimo-studio view read VIEW DOCUMENT [--target PATH]
marimo-studio view write VIEW DOCUMENT [--target PATH] --expected-revision REVISION --from FILE|-
marimo-studio view build VIEW [--target PATH]
marimo-studio view activate VIEW [--target PATH] --server URL
marimo-studio view export VIEW [--target PATH] --output DIRECTORY
marimo-studio view remove VIEW [--target PATH]

marimo-studio validate [VIEW] [--target PATH] [--level static|runtime|browser]
marimo-studio doctor [PROVIDER]
```

Use `--format json` for result data and `--diagnostics jsonl` for one
diagnostic event per stderr line. JSON results stay on stdout. Provider,
runtime, and child-process output stays on stderr.

## Exit status

| Exit  | Meaning                                     |
| ----- | ------------------------------------------- |
| `0`   | The requested operation completed           |
| `1`   | Validation found a failed contract          |
| `2`   | Arguments or capability input are invalid   |
| `3`   | Configuration or authored source is invalid |
| `4`   | A notebook cell binding is invalid          |
| `5`   | A live Studio request failed                |
| `6`   | The installed protocol is incompatible      |
| `7`   | The notebook environment cannot be prepared |
| `130` | The command was interrupted                 |

## JSON results

Every JSON result contains `schema`. The main command-specific fields are:

| Command            | Fields                                                                                         |
| ------------------ | ---------------------------------------------------------------------------------------------- |
| `status`           | `notebook`, `state`, `config`, `default_view`, `runtimes`, `bindings`, `views`                 |
| `notebook inspect` | `notebook`, `app_config`, `cells`, and `runtime` when requested                                |
| `notebook bind`    | `alias`, `cell`, `config`, `dry_run`, `previous_ref`, `changed`                                |
| `starters`         | `starters`                                                                                     |
| `view create`      | `notebook`, `config`, `view`, `root`, `provider`, `documents`, `created`, `updated`, `dry_run` |
| `view inspect`     | `view`, `provider`, `documents`, `diagnostics`, `freshness`, `publication`                     |
| `view read`        | `path`, `language`, `access`, `content`, `revision`                                            |
| `view write`       | `path`, `language`, `access`, `content`, `revision`                                            |
| `view build`       | `view`, `profile`, `input_id`, `artifact_id`, `diagnostics`, `duration_ms`                     |
| `view activate`    | `notebook`, `view`, `generation`, `client_id`, `session_id`                                    |
| `view export`      | `notebook`, `view`, `runtime`, `output`, `entrypoint`, `files`                                 |
| `view remove`      | `notebook`, `view`, `default_view`, `views`                                                    |
| `validate`         | `notebook`, `view`, `level`, `ok`, `handoff_ready`, `actions`, `evidence`                      |
| `doctor`           | `providers`                                                                                    |

Diagnostic events contain `event`, `command`, `code`, `severity`, and
`message`. Process and command failures add `exit_code`. A diagnostic may add
`status` and structured `details`.

## Inspect the workspace

```console
marimo-studio status --target analysis.py
marimo-studio notebook inspect --target analysis.py \
  --cell summary \
  --include-code \
  --format json
```

`status` returns configuration and the view inventory. `notebook inspect`
returns saved cell identities, definitions, references, and dependency edges.
Repeat `--cell` to select cells by ref, name, or zero-based index. Add
`--runtime` to execute the complete notebook and collect bounded MIME outputs
and JSON values for the selected cells.

## Create a view

```console
marimo-studio starters --format json
marimo-studio view create dashboard \
  --target analysis.py \
  --starter marimo-studio/vanilla:default
```

`view create` rejects an existing view name. `--dry-run` returns the planned
writes. The new view remains `unbuilt` until a build or live preview publishes
an artifact.

## Inspect and edit source

```console
marimo-studio view inspect dashboard \
  --target analysis.py \
  --format json

marimo-studio view read dashboard index.html \
  --target analysis.py \
  --format json
```

`view inspect` returns the provider document catalog, diagnostics, freshness,
and current publication. `view read` returns one document and its revision.
Pass that revision to `view write` so a concurrent save reports a source
conflict.

```console
cat updated-index.html | marimo-studio view write dashboard index.html \
  --target analysis.py \
  --expected-revision sha256:CURRENT_REVISION \
  --from -
```

Studio validates document access, compares the current revision, preserves the
file mode, and replaces the source atomically.

## Build and activate

```console
marimo-studio view build dashboard --target analysis.py
marimo-studio view activate dashboard \
  --target analysis.py \
  --server http://localhost:2718 \
  --browser-client CLIENT_ID
```

`view build` publishes a validated artifact. A failed candidate leaves the
current publication available. `--profile development|production` selects the
build profile. Activation targets one connected Studio browser. Set
`MARIMO_STUDIO_ACCESS_TOKEN` when the server requires authentication.

## Validate

```console
marimo-studio validate dashboard --target analysis.py --level static
marimo-studio validate dashboard --target analysis.py --level runtime
marimo-studio validate dashboard \
  --target analysis.py \
  --level browser \
  --server http://localhost:2718
```

Validation levels are cumulative:

| Level     | Evidence                                                          |
| --------- | ----------------------------------------------------------------- |
| `static`  | Saved notebook, view source, configuration, and target resolution |
| `runtime` | Static evidence plus complete isolated notebook execution         |
| `browser` | Runtime evidence plus the selected rendered Studio client         |

The default level is `static`. Omit `VIEW` to validate every configured view.
Runtime validation can perform the notebook's configured file, network,
database, and data access.

## Export and remove

```console
marimo-studio view export dashboard \
  --target analysis.py \
  --output dist/dashboard

marimo-studio view remove dashboard --target analysis.py
```

Export builds the production artifact and writes a static WebAssembly site.
Use `--force` to replace an existing destination. Removal confirms before it
deletes the view project. Pass `--yes` for reviewed non-interactive removal.
A configured notebook retains at least one view.

## Diagnose providers

```console
marimo-studio doctor
marimo-studio doctor acme-views/report --format json
```

`doctor` reports provider registration, package version, availability, and
provider-qualified starter IDs.
