---
title: CLI
description: Inspect notebooks and create, edit, build, show, validate, export, and remove Studio pages.
---

# CLI

`marimo-studio` works with saved notebooks. Pass `--target` a notebook,
project directory, or `pyproject.toml`. When omitted, Studio looks for one
configured notebook from the current directory.

Add `--json` when another program will read the result. Studio writes one JSON
result to stdout and JSON Lines diagnostic events to stderr.

## `marimo-studio doctor`

```text
marimo-studio doctor [PROVIDER] [--json]
```

Lists installed frontend integrations, their package versions, availability,
and page starting points. A named provider exits with status `1` when it cannot
load or build in the current environment. The full inventory remains available
when another optional provider is unavailable.

## `marimo-studio starters`

```text
marimo-studio starters [--json]
```

Lists the installed choices for new page source. Each result includes the ID
accepted by `view create --starter`, the files it creates, and the setup action
for an unavailable choice.

## `marimo-studio status`

```text
marimo-studio status [--target PATH] [--json]
```

Returns the notebook, active configuration source, default view, allowed
runtimes, cell aliases, and named views. An unconfigured notebook includes the
command that creates its first page.

## `marimo-studio notebook inspect`

```text
marimo-studio notebook inspect [--target PATH] [--cell SELECTOR] [--json]
```

Inspects saved cells, names, definitions, references, and dependency edges.
Repeat `--cell` to select a cell by name, stable ref, or zero-based index.

`--include-code` returns complete selected cell source. `--runtime` executes the
complete notebook and adds bounded MIME outputs and JSON-compatible values.
`--context upstream` adds every cell that produces a selected cell's inputs.
`--runtime-timeout` controls how long that execution may run.

## `marimo-studio notebook bind`

```text
marimo-studio notebook bind ALIAS --cell SELECTOR [--target PATH] [--json]
```

Gives one existing notebook cell a stable name for page source. `--dry-run`
reports the change. `--overwrite` replaces an existing alias.

## `marimo-studio view create`

```text
marimo-studio view create VIEW [--target PATH] [--starter ID] [--json]
```

Creates one named page and rejects an existing name. The default choice creates
one editable HTML file. `--starter` selects another installed starting point.
`--dry-run` reports every planned write.

## `marimo-studio view inspect`

```text
marimo-studio view inspect VIEW [--target PATH] [--json]
```

Returns editable and read-only source files, current diagnostics, build
freshness, and the latest successful build.

## `marimo-studio view read`

```text
marimo-studio view read VIEW DOCUMENT [--target PATH] [--json]
```

Reads one allowed text file and its current source revision.

## `marimo-studio view write`

```text
marimo-studio view write VIEW DOCUMENT --expected-revision REVISION --from FILE|- [--target PATH] [--json]
```

Reads UTF-8 content from a file or stdin, checks that the source revision still
matches, then replaces the file atomically. A concurrent save returns a source
conflict and preserves the newer file.

## `marimo-studio view build`

```text
marimo-studio view build VIEW [--target PATH] [--profile development|production] [--json]
```

Builds and validates one page. `development` updates authoring Preview.
`production` prepares run mode and export. A failed build leaves the last
successful page available.

## `marimo-studio view show`

```text
marimo-studio view show VIEW --server URL [--target PATH] [--browser-client ID] [--json]
```

Shows the view in a connected Studio tab. Set `MARIMO_STUDIO_SERVER_URL` instead
of `--server` when the URL is already known. Set
`MARIMO_STUDIO_ACCESS_TOKEN` when the server requires authentication.

Studio selects the connected tab automatically when there is one. When several
tabs are connected, the error lists their IDs. Pass one through
`--browser-client` or `MARIMO_STUDIO_BROWSER_CLIENT`.

## `marimo-studio view export`

```text
marimo-studio view export VIEW --output DIRECTORY [--target PATH] [--force] [--json]
```

Builds the production page and writes a static browser site. The result includes
the exact entry file. `--force` replaces an existing output directory after its
boundary has been validated.

The exported directory contains the notebook source.

## `marimo-studio view remove`

```text
marimo-studio view remove VIEW [--target PATH] [--yes] [--json]
```

Confirms before deleting the page and its source files. `--yes` is required for
machine-readable or non-interactive use. A configured notebook keeps at least
one view.

## `marimo-studio validate`

```text
marimo-studio validate [VIEW] [--target PATH] [--level static|runtime|browser] [--server URL] [--browser-client ID] [--browser-timeout SECONDS] [--runtime-timeout SECONDS] [--json]
```

Validation grows with the selected level:

| Level     | Evidence                                                              |
| --------- | --------------------------------------------------------------------- |
| `static`  | Saved notebook, page source, configuration, and notebook-result names |
| `runtime` | Static evidence plus complete isolated notebook execution             |
| `browser` | Runtime evidence plus the selected rendered Studio page               |

The default level is `static`. Omit `VIEW` to validate every configured view at
the static or runtime level. Browser validation requires one view and a running
Studio server. Studio selects the connected tab when there is one. With several
tabs, pass the intended ID through `--browser-client` or
`MARIMO_STUDIO_BROWSER_CLIENT`. `--runtime-timeout` bounds isolated notebook
execution. `--browser-timeout` bounds the wait for current rendered evidence.

## Exit status

|  Exit | Meaning                                            |
| ----: | -------------------------------------------------- |
|   `0` | The requested operation completed                  |
|   `1` | Validation or a named provider check failed        |
|   `2` | Arguments or capability input are invalid          |
|   `3` | Configuration or saved source is invalid           |
|   `4` | A notebook cell alias is invalid                   |
|   `5` | A live Studio request failed                       |
|   `6` | The installed Studio and marimo protocols disagree |
|   `7` | The notebook environment cannot be prepared        |
| `130` | The command was interrupted                        |
