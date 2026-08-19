---
title: CLI reference
description: Commands, options, machine output, diagnostics, and exit codes for marimo-studio.
---

# CLI reference

`marimo-studio` reports workspace state, creates and activates view source,
inspects notebook cells, records stable aliases, validates projections, and
exports static sites. Marimo's `edit` and `run` commands own notebook servers.

```text
marimo-studio overview [OPTIONS] [TARGET]
marimo-studio inspect [OPTIONS] [TARGET]
marimo-studio bind [OPTIONS] [TARGET]
marimo-studio view add [OPTIONS] [TARGET]
marimo-studio view activate [OPTIONS] [TARGET]
marimo-studio view remove [OPTIONS] [TARGET]
marimo-studio analyze [OPTIONS] [TARGET]
marimo-studio check [OPTIONS] [TARGET]
marimo-studio export [OPTIONS] [TARGET]
```

`TARGET` accepts a notebook path, project directory, or `pyproject.toml`. Pass
a notebook path when creating the first view. Commands discover one configured
notebook from the current directory when `TARGET` is omitted.

Every data command accepts:

| Option                      | Default | Behavior                                                          |
| --------------------------- | ------- | ----------------------------------------------------------------- |
| `--format text\|json`       | `text`  | Write human text or stable JSON to standard output                |
| `--diagnostics text\|jsonl` | `text`  | Write human diagnostics or one JSON event per standard-error line |

::: warning Runtime mode executes notebook code
`analyze`, `inspect --runtime`, and `check --runtime` can perform the
notebook's file, network, database, and data access. Run them in the notebook
environment.
:::

## `overview`

```console
uvx marimo-studio overview analysis.py --format json
```

Reports the saved notebook, configuration state, canonical view root, default
view and runtime, cell bindings, and every authored view. It works before the
notebook has Studio configuration and returns one of these states:

| State          | Meaning                                                 |
| -------------- | ------------------------------------------------------- |
| `unconfigured` | The notebook has no Studio definition                   |
| `needs-view`   | Studio configuration exists and awaits its first view   |
| `ready`        | The configured default and authored views are available |

JSON output is the same `StudioOverview` record returned by
`marimo_studio.agent.overview`.

## `inspect`

```console
uvx marimo-studio inspect analysis.py --display
```

Compiles the notebook graph and prints one record per selected cell.

| Option                      | Behavior                                                                       |
| --------------------------- | ------------------------------------------------------------------------------ |
| `--display`                 | Keep cells whose body ends with a displayed expression                         |
| `--include-code`            | Include each complete cell body                                                |
| `--runtime`                 | Execute the notebook and include MIME outputs and JSON-compatible values       |
| `--limit N`                 | Return at most `N` cell records, where `N` is at least 1                       |
| `--runtime-timeout SECONDS` | Wait 0 to 300 finite seconds for runtime inspection. The default is 60 seconds |

Static inspection leaves cell bodies unevaluated.

## `bind`

```console
uvx marimo-studio bind analysis.py --cell 12 --as summary
```

Records `summary` as a stable alias for zero-based cell index `12`.

| Option         | Behavior                                             |
| -------------- | ---------------------------------------------------- |
| `--cell INDEX` | Select the zero-based cell. Required                 |
| `--as ALIAS`   | Name the selected cell. Required                     |
| `--dry-run`    | Report the binding and leave configuration unchanged |
| `--overwrite`  | Replace an existing alias                            |

Use a native Marimo cell name directly when one exists. An alias starts with a
letter and contains letters, digits, underscores, or hyphens.

An alias follows its cell across formatting and comment changes. Reinspect the
notebook before using `--overwrite` after the cell's Python meaning changes or
its match becomes ambiguous.

## `view add`

```console
uvx marimo-studio view add analysis.py
```

Creates the `dashboard` view directory and configures the notebook when needed.
A new view contains `index.html` and `app.css` and starts with every notebook
cell in source order.

Name another view with `--name`:

```console
uvx marimo-studio view add analysis.py --name executive
```

`--dry-run` reports the files and configuration changes without writing them.

A view name starts with a lowercase letter and contains lowercase letters,
digits, or hyphens. Names claimed by Marimo or Studio routes are reserved.

## `view activate`

```console
MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
  uvx marimo-studio view activate analysis.py \
    --name dashboard \
    --format json
```

Activates the named view in one connected Studio browser. Pass
`--browser-client ID` or `MARIMO_STUDIO_BROWSER_CLIENT` when several tabs are
connected. With no ID, the command requires exactly one connected browser.

`--server` or `MARIMO_STUDIO_SERVER_URL` identifies the running Studio server.
Set `MARIMO_STUDIO_ACCESS_TOKEN` for authentication. JSON output is the same
`ViewActivationResult` returned by `marimo_studio.agent.activate_view` and
includes the selected browser client, Marimo session, transition, and
activation generation.

An explicit `--server` or `--browser-client` value overrides its environment
variable. Activation reports stable codes such as `view-not-found`,
`browser-client-ambiguous`, `browser-client-unavailable`,
`browser-session-unavailable`, and `activation-timeout` through JSON Lines
diagnostics.

## `view remove`

```console
uvx marimo-studio view remove analysis.py --name executive
```

Removes the named view directory after confirmation. If the selected view is
the default, the first remaining view becomes the default. A configured
notebook retains at least one view.

Use `--yes` for a reviewed non-interactive removal. JSON output includes
`schema`, `notebook`, `view`, `default_view`, and the remaining `views`.

## `check`

```console
uvx marimo-studio check analysis.py --view dashboard --runtime
```

Static checks validate view documents, aliases, and value selectors. Add
`--runtime` to execute projected cells and resolve projected values. Omit
`--view` to check every configured view. Runtime execution waits 60 seconds by
default. Set `--runtime-timeout SECONDS` for notebooks with expected setup work
such as remote data loading.

Text output reports one `PASS`, `WARN`, or `FAIL` record per check. JSON output
contains `schema`, `ok`, `notebook`, `view`, and a `checks` array. Its
`compatibility` records the Studio version, required Marimo release, observed
Marimo and browser identities, adapter family, and validation state. Observed
identities are `null` when release validation fails.

## `analyze`

```console
MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
  uvx marimo-studio analyze analysis.py \
    --view dashboard \
    --format json \
    --diagnostics jsonl
```

Runs the complete agent handoff gate. Static validation reads the notebook and
view sources. Runtime validation executes the notebook and resolves every
projected output and value. Browser validation asks a connected Studio tab to
visit each selected view and return fresh readiness and diagnostics for the
captured source revision, runtime instance, and Marimo session.

| Option                       | Behavior                                                                                                      |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `--view NAME`                | Analyze one named view. The default analyzes every configured view                                            |
| `--server URL`               | Request rendered evidence from this running Studio server. `MARIMO_STUDIO_SERVER_URL` provides the same value |
| `--browser-client ID`        | Target one Studio tab when several tabs are connected. `MARIMO_STUDIO_BROWSER_CLIENT` provides the same value |
| `--browser-timeout SECONDS`  | Wait 0 to 300 finite seconds for fresh rendered evidence. The default is 10 seconds                           |
| `--runtime-timeout SECONDS`  | Wait 0 to 300 finite seconds for isolated notebook execution. The default is 60 seconds                       |
| `--browser` / `--no-browser` | Require or skip current rendered evidence. Browser evidence is required by default                            |

Set `MARIMO_STUDIO_ACCESS_TOKEN` to authenticate. The command rejects access
tokens embedded in `--server` URLs so credentials stay out of shell history
and process arguments.

The Studio bootstrap record contains its browser client ID. With several tabs
open for one notebook, read `clientId` from the target tab's
`#marimo-studio-bootstrap` JSON and pass it through `--browser-client` or the
environment variable. Browser selection requires `--server` or
`MARIMO_STUDIO_SERVER_URL`. Supplying a client ID without a server is a usage
error with exit code 2.

The JSON response contains:

- `ok`, which is true when no stage reports an error
- `handoff_ready`, which also requires completed runtime validation and a
  `ready` browser observation for every selected view
- `stages.static`, `stages.runtime`, and `stages.browser`
- `runtime` and `revisions`, which identify the evidence set
- `actions`, an ordered repair queue with stage, severity, code, message,
  advice, and available view, target, or source location

A runtime deadline produces a `runtime-timeout` action. Increase
`--runtime-timeout` when the notebook is expected to spend longer on setup.
Otherwise, fix the notebook operation named by the runtime output.

In the default browser-required mode, omitting the server URL returns static
and runtime results with a `not-observed` browser stage. `handoff_ready` is
false and the command exits with code 1. Open the selected view in Studio,
provide its server URL, and rerun the command before handoff. Use
`--no-browser` for an explicit source and runtime gate. A passing gate can then
return `handoff_ready` without rendered evidence.

## `export`

```console
uvx marimo-studio export analysis.py \
  --view dashboard \
  --output dist/dashboard
```

Writes the selected view as a static WebAssembly site. The configured default
view is selected when `--view` is absent.

| Option             | Behavior                                          |
| ------------------ | ------------------------------------------------- |
| `-o, --output DIR` | Write the complete static site to `DIR`. Required |
| `--view NAME`      | Export a named view                               |
| `--force`          | Replace an existing output directory              |

The command validates projected cells, values, and output paths before writing
the export. JSON output includes the selected view, runtime, output directory,
entry point, and file count.

Serve the directory over HTTP so the browser can load worker modules and
runtime assets. [Run, export, and
share](../guide/run-and-share.md#export-a-static-site) covers the notebook-source
and browser-network boundaries.

## Machine diagnostics

Use JSON output and JSON Lines diagnostics when another program or agent will
consume the result:

```console
uvx marimo-studio analyze analysis.py \
  --view dashboard \
  --server http://localhost:2718 \
  --format json \
  --diagnostics jsonl
```

Each diagnostic event contains:

```json
{
  "schema": 1,
  "event": "diagnostic",
  "command": "analyze",
  "severity": "error",
  "code": "cell-not-found",
  "message": "Cell 'summary' is not defined in the notebook.",
  "status": "fail"
}
```

Projection diagnostics can also include the view, target, source location, and
repair hint. Command failures include `exit_code`. Native process output is
bounded and emitted as a warning event when JSON Lines diagnostics are active.
Transport failures use stable codes such as `authentication-required`,
`request-timeout`, and `request-capacity-exhausted` so an agent can retry the
right boundary or reduce concurrent requests.

## Exit codes

|  Code | Meaning                                                       |
| ----: | ------------------------------------------------------------- |
|   `0` | Command completed                                             |
|   `1` | Validation failed or rendered evidence is incomplete          |
|   `2` | CLI syntax or option usage is invalid                         |
|   `3` | Notebook or Studio configuration is invalid                   |
|   `4` | A cell binding cannot be resolved                             |
|   `5` | A live Studio server or browser request failed                |
|   `6` | A Studio protocol or installed Marimo version is incompatible |
|   `7` | The notebook environment cannot be prepared                   |
| `130` | The command was interrupted                                   |

[Notebook configuration](configuration.md) defines target discovery and
configuration precedence.
