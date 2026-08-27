---
title: CLI reference
description: Create, inspect, build, validate, activate, export, and extend Studio views.
---

# CLI reference

`marimo-studio` works with saved notebooks. `TARGET` may be a notebook, a
project directory, or `pyproject.toml`. The current directory is used when it
contains one configured notebook.

```text
marimo-studio overview [TARGET]
marimo-studio inspect [TARGET]
marimo-studio bind [TARGET]

marimo-studio starter list
marimo-studio starter show STARTER_ID

marimo-studio view create [TARGET] [--name NAME] [--starter STARTER_ID]
marimo-studio view inspect [TARGET] --name NAME
marimo-studio view build [TARGET] --name NAME
marimo-studio view activate [TARGET] --name NAME --server URL
marimo-studio view remove [TARGET] --name NAME

marimo-studio validate [TARGET] [--view NAME] --level static|runtime|browser
marimo-studio export [TARGET] --view NAME --output DIRECTORY
marimo-studio provider doctor [PROVIDER]
```

Use `--format json` for data and `--diagnostics jsonl` for one diagnostic event
per stderr line.

With `--format json`, stdout contains one result document. Provider, runtime,
and child-process output stays on stderr. JSONL diagnostics bound that output
and report it as `process-output` events.

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

| Command           | Fields                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `overview`        | `notebook`, `state`, `config`, `config_source`, `view_root`, `default_view`, `default_runtime`, `runtimes`, `bindings`, `views` |
| `inspect`         | `notebook`, `app_config`, `cells`, and `runtime` when requested                                                                 |
| `bind`            | `alias`, `cell`, `config`, `dry_run`, `previous_ref`, `changed`                                                                 |
| `starter list`    | `starters`                                                                                                                      |
| `starter show`    | `id`, `title`, `summary`, `provider`, `documents`, `availability`                                                               |
| `view create`     | `notebook`, `config`, `view`, `root`, `provider`, `documents`, `created`, `updated`, `dry_run`                                  |
| `view inspect`    | `view`, `provider`, `documents`, `diagnostics`, `freshness`, `publication`                                                      |
| `view build`      | `view`, `profile`, `input_id`, `artifact_id`, `diagnostics`, `duration_ms`                                                      |
| `view activate`   | `notebook`, `view`, `generation`, `client_id`, `session_id`                                                                     |
| `view remove`     | `notebook`, `view`, `default_view`, `views`                                                                                     |
| `validate`        | `notebook`, `view`, `level`, `ok`, `handoff_ready`, `actions`, `evidence`                                                       |
| `export`          | `notebook`, `view`, `runtime`, `output`, `entrypoint`, `files`                                                                  |
| `provider doctor` | `providers`                                                                                                                     |

`overview`, `view create`, and `view activate` emit schema 2 records. The
remaining command records emit schema 1.

Diagnostic events contain `event`, `command`, `code`, `severity`, and
`message`. Process and command failures add `exit_code`. A diagnostic may also
add `status` and structured `details`.

## Create a view

```console
marimo-studio starter list
marimo-studio view create analysis.py \
  --name dashboard \
  --starter marimo-studio/vanilla:default
```

`starter list` reports provider-qualified IDs. Omitting `--starter` selects
`marimo-studio/vanilla:default`.

The default starter creates:

```text
dashboard/
  view.toml
  index.html
```

`view create` fails when the name already exists. `--dry-run` reports planned
writes. The view remains `unbuilt` until an explicit build or live preview
publishes `.artifacts/`. A view name starts with a lowercase letter and
contains lowercase letters, numbers, or hyphens.

## Inspect and build

```console
marimo-studio view inspect analysis.py --name dashboard --format json
marimo-studio view build analysis.py --name dashboard
```

`view inspect` returns the provider, source documents and access, diagnostics,
build freshness, and the current publication. Projection declarations and
runtime evidence are returned by `validate`. `view build` writes a candidate to
generated staging, validates it, and atomically publishes it. A failed build
keeps the last published page available.

`--profile development|production` selects the build profile. The default is
`development`.

## Validate

```console
marimo-studio validate analysis.py --view dashboard --level static
marimo-studio validate analysis.py --view dashboard --level runtime
marimo-studio validate analysis.py --view dashboard --level browser --server http://localhost:2718
```

Validation levels are cumulative:

| Level     | Evidence                                                          |
| --------- | ----------------------------------------------------------------- |
| `static`  | Saved notebook, view source, configuration, and target resolution |
| `runtime` | Static evidence plus complete isolated notebook execution         |
| `browser` | Runtime evidence plus the selected rendered Studio client         |

Use `--browser-client ID` when several browser clients are connected. Set
`MARIMO_STUDIO_ACCESS_TOKEN` when the running server requires authentication.
`--runtime-timeout` and `--browser-timeout` accept finite seconds from 0 to 300.
Runtime validation can perform the notebook's configured file, network,
database, and data access before Studio checks the selected projected results.

## Activate a browser

```console
marimo-studio view activate analysis.py \
  --name dashboard \
  --server http://localhost:2718 \
  --browser-client CLIENT_ID
```

Activation targets one connected browser. The client selector is required when
the server cannot choose a single client unambiguously.

## Export

```console
marimo-studio export analysis.py --view dashboard --output dist/dashboard
```

Export builds the production artifact and writes a static WebAssembly site.
Use `--force` to replace a reviewed destination.

## Remove a view

```console
marimo-studio view remove analysis.py --name dashboard
```

Removal deletes the view directory after confirmation. It does not rewrite
Python dependencies. A configured notebook retains at least one view. Use
`--yes` for reviewed non-interactive removal.

## Diagnose an extension

```console
marimo-studio provider doctor
marimo-studio provider doctor acme-views/report --format json
```

`provider doctor` reports entry-point loading, package version, availability,
and provider-qualified starter IDs.

## Inspect notebook cells

```console
marimo-studio inspect analysis.py --cell summary --include-code
marimo-studio bind analysis.py --cell 12 --as summary
```

`inspect` reads the saved notebook graph. Repeat `--cell` to select cells by
reference, name, or zero-based index. Add `--runtime` to include their MIME
outputs and JSON-compatible values. `bind` gives an anonymous cell a stable
target when naming the Marimo cell directly is not practical.

::: warning Runtime inspection executes the complete notebook
Cell selectors bound collected source, outputs, and values. Marimo still runs
the notebook's reactive graph to produce those results.
:::
