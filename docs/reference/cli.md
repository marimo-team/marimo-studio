---
title: CLI reference
description: Commands, options, machine output, diagnostics, and exit codes for marimo-studio.
---

# CLI reference

`marimo-studio` creates view source, inspects notebook cells, records stable
aliases, validates projections, and exports static sites. Marimo's `edit` and
`run` commands own notebook servers.

```text
marimo-studio inspect [OPTIONS] [TARGET]
marimo-studio bind [OPTIONS] [TARGET]
marimo-studio view add [OPTIONS] [TARGET]
marimo-studio view list [OPTIONS] [TARGET]
marimo-studio view remove [OPTIONS] [TARGET]
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
`inspect --runtime` and `check --runtime` can perform the notebook's file,
network, database, and data access. Run them in the notebook environment.
:::

## `inspect`

```console
uvx marimo-studio inspect analysis.py --display
```

Compiles the notebook graph and prints one record per selected cell.

| Option           | Behavior                                                                 |
| ---------------- | ------------------------------------------------------------------------ |
| `--display`      | Keep cells whose body ends with a displayed expression                   |
| `--include-code` | Include each complete cell body                                          |
| `--runtime`      | Execute the notebook and include MIME outputs and JSON-compatible values |
| `--limit N`      | Return at most `N` cell records, where `N` is at least 1                 |

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

## `view list`

```console
uvx marimo-studio view list analysis.py
```

Lists every configured view, its source directory, and the current default.
JSON output includes `schema`, `notebook`, `default_view`, and a `views` array.

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
`--view` to check every configured view.

Text output reports one `PASS`, `WARN`, or `FAIL` record per check. JSON output
contains `schema`, `ok`, `notebook`, `view`, and a `checks` array.

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
uvx marimo-studio check analysis.py \
  --runtime \
  --format json \
  --diagnostics jsonl
```

Each diagnostic event contains:

```json
{
  "schema": 1,
  "event": "diagnostic",
  "command": "check",
  "severity": "error",
  "code": "cell-not-found",
  "message": "Cell 'summary' is not defined in the notebook.",
  "status": "fail"
}
```

Projection diagnostics can also include the view, target, source location, and
repair hint. Command failures include `exit_code`. Native process output is
bounded and emitted as a warning event when JSON Lines diagnostics are active.

## Exit codes

|  Code | Meaning                                      |
| ----: | -------------------------------------------- |
|   `0` | Command completed                            |
|   `1` | Validation found failures                    |
|   `2` | CLI syntax or option usage is invalid        |
|   `3` | Notebook or Studio configuration is invalid  |
|   `4` | A cell binding cannot be resolved            |
|   `6` | The installed Marimo version is incompatible |
|   `7` | The notebook environment cannot be prepared  |
| `130` | The command was interrupted                  |

[Notebook configuration](configuration.md) defines target discovery and
configuration precedence.
