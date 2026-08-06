---
title: CLI reference
description: Commands, options, machine output, diagnostics, and exit codes for marimo-studio.
---

# CLI reference

`marimo-studio` creates view source, inspects notebook cells, records stable
aliases, validates projections, and exports static sites. Marimo's `edit` and
`run` commands own notebook servers.

```text
marimo-studio inspect [OPTIONS] [NOTEBOOK]
marimo-studio bind [OPTIONS] ALIAS [NOTEBOOK]
marimo-studio view add [OPTIONS] NAME [NOTEBOOK]
marimo-studio view list [OPTIONS] [NOTEBOOK]
marimo-studio check [OPTIONS] [NOTEBOOK]
marimo-studio export [OPTIONS] [NOTEBOOK]
```

Pass a notebook path when creating the first view. Later commands can discover
one configured notebook from the current directory or its project.

Every data command accepts:

| Option                      | Default | Behavior                                                          |
| --------------------------- | ------- | ----------------------------------------------------------------- |
| `--format text\|json`       | `text`  | Write human text or stable JSON to standard output                |
| `--diagnostics text\|jsonl` | `text`  | Write human diagnostics or one JSON event per standard-error line |

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

Static inspection leaves cell bodies unevaluated. Runtime inspection can
perform the notebook's file, network, database, and data access.

## `bind`

```console
uvx marimo-studio bind summary analysis.py --cell 12
```

Records `summary` as a stable alias for zero-based cell index `12`.

| Option         | Behavior                                             |
| -------------- | ---------------------------------------------------- |
| `--cell INDEX` | Select the zero-based cell. Required                 |
| `--dry-run`    | Report the binding and leave configuration unchanged |
| `--overwrite`  | Replace an existing alias                            |

Use a native Marimo cell name directly when one exists. An alias starts with a
letter and contains letters, digits, underscores, or hyphens.

An alias follows its cell across formatting and comment changes. Reinspect the
notebook before using `--overwrite` after the cell's Python meaning changes or
its match becomes ambiguous.

## `view add`

```console
uvx marimo-studio view add executive analysis.py
```

Creates the view directory and configures the notebook when needed. A new view
contains `index.html` and `app.css` and starts with every notebook cell in
source order.

`--dry-run` reports the files and configuration changes without writing them.

A view name starts with a lowercase letter and contains lowercase letters,
digits, or hyphens. Names claimed by Marimo or Studio routes are reserved.

## `view list`

```console
uvx marimo-studio view list analysis.py
```

Lists every configured view, its source directory, and the current default.
JSON output includes `schema`, `notebook`, `default_view`, and a `views` array.

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
runtime assets. [Run and share views](share-views.md#export-a-static-site)
covers the notebook-source and browser-network boundaries.

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
