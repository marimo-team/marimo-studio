---
title: CLI
description: Inspect notebooks and create, edit, build, show, validate, export, and remove Studio views.
---

# CLI

`marimo-studio` works with saved notebooks. Pass `--target` a notebook,
project directory, or `pyproject.toml`. When omitted, Studio looks for one
configured notebook from the current directory.

Prefix a one-off command with `uvx`, as in `uvx marimo-studio status`. Use
`uv run marimo-studio` inside a project that pins Studio.

Add `--json` when another program will read the result. Studio writes one JSON
result to stdout and JSON Lines diagnostic events to stderr.

::: warning Provider-backed commands execute trusted code
Commands such as `doctor`, `starters`, `status`, `view create`, `view inspect`,
`view read`, `view write`, `view build`, `view export`, and `validate` can invoke
installed providers. Third-party provider code runs with the current user's
filesystem, environment, and network authority. Review provider packages before
running these commands or installing their launch requirements.
:::

## Provider environments

`status`, `view create`, `view inspect`, `view read`, `view write`, `view build`,
`view export`, and `validate` read provider IDs from saved `view.toml` files
before provider code loads. Studio derives built-in requirements such as
`marimo-studio[deno]` from those IDs and reads third-party provider requirements
from the notebook's PEP 723 block or project `pyproject.toml`.

When the current process does not satisfy those requirements, Studio reruns the
command through `uv`. `uv` may resolve and install packages before provider code
loads. A third-party key such as `acme-views/report` requires an active
`acme-views` dependency in the notebook or project.

Reading or repairing `view.toml` uses Studio's provider-independent manifest
path in the current process. This keeps the manifest available when its provider
is unavailable or its content needs repair.

## `marimo-studio doctor`

```text
marimo-studio doctor [PROVIDER] [--json]
```

Lists installed frontend integrations, their package versions, availability,
and view starting points. A named provider exits with status `1` when it cannot
load or build in the current environment. The full inventory remains available
when another optional provider is unavailable.

## `marimo-studio starters`

```text
marimo-studio starters [--json]
```

Lists the installed choices for new view source. Each result includes the ID
accepted by `view create --starter`, the files it creates, and the setup action
for an unavailable choice.

## `marimo-studio status`

```text
marimo-studio status [--target PATH] [--json]
```

Returns the notebook, active configuration source, default view, allowed
runtimes, cell aliases, named views, and exact `launch_requirements` for Studio
and configured provider distributions. An unconfigured notebook includes the
command that creates its first view. The command inspects every configured view
through its provider.

## `marimo-studio notebook inspect`

```text
marimo-studio notebook inspect [--target PATH] [--cell SELECTOR]...
  [--include-code] [--output-expressions] [--runtime] [--limit COUNT]
  [--context selected|upstream] [--runtime-timeout SECONDS] [--json]
```

Inspects saved cells, names, definitions, references, and dependency edges.
Repeat `--cell` to select a cell by name, stable ref, or zero-based index.

`--include-code` returns complete selected cell source. `--runtime` executes the
complete notebook and adds bounded MIME outputs and JSON-compatible values.
`--context upstream` adds every cell that produces a selected cell's inputs.
`--runtime-timeout` controls how long that execution may run.

## `marimo-studio notebook bind`

```text
marimo-studio notebook bind ALIAS --cell SELECTOR [--target PATH]
  [--dry-run] [--overwrite] [--json]
```

Gives one existing notebook cell a stable name for view source. `--dry-run`
reports the change. `--overwrite` replaces an existing alias.

## `marimo-studio view create`

```text
marimo-studio view create VIEW [--target PATH] [--starter ID] [--dry-run] [--json]
```

Creates one named view and rejects an existing name. The default choice creates
one editable HTML file and exposes its directly referenced local CSS and
JavaScript files. `--starter` selects another installed starting point.
`--dry-run` reports every planned write.

A completed creation returns exact `launch_requirements` in JSON and prints the
next `uvx` command with one `--with` argument for each requirement. Install and
run requirements for reviewed providers.

## `marimo-studio view inspect`

```text
marimo-studio view inspect VIEW [--target PATH] [--json]
```

Returns editable and read-only source files, current diagnostics, development
build freshness, and the latest successful development build used by Preview.

## `marimo-studio view read`

```text
marimo-studio view read VIEW DOCUMENT [--target PATH] [--json]
```

Reads one allowed text file and its current source revision.

Use `--json` before editing. The JSON result includes `revision`,
`catalog_generation`, and `view_generation` from the same source read. Human
output includes a path and revision header before the content.

## `marimo-studio view write`

```text
marimo-studio view write VIEW DOCUMENT --expected-revision REVISION
  --catalog-generation GENERATION --view-generation GENERATION
  --from FILE|- [--target PATH] [--json]
```

Reads UTF-8 content from a file or stdin. The write succeeds when the source
revision, workspace catalog generation, and view generation still match the
preceding JSON read. A conflict preserves the current file. Read the document
again, review its content, and retry with the new preconditions. Both generation
flags accept the 64-character lowercase hexadecimal values returned by
`view read --json`.

Use `view remove` and `view create` for same-name replacement. Direct filesystem
delete and recreation completed between observations is outside the 0.1
mutation-ownership contract when it reuses `(device, inode, mode)`. This includes
exact-byte recreation.

```sh
marimo-studio view read dashboard index.html --target analysis.py --json > source.json
jq -j .content source.json > index.html

marimo-studio view write dashboard index.html --target analysis.py \
  --expected-revision "$(jq -r .revision source.json)" \
  --catalog-generation "$(jq -r .catalog_generation source.json)" \
  --view-generation "$(jq -r .view_generation source.json)" \
  --from index.html
```

The same flow repairs `view.toml` when provider inspection is unavailable.

## `marimo-studio view build`

```text
marimo-studio view build VIEW [--target PATH] [--profile development|production] [--json]
```

Builds and validates one view. `development` updates authoring Preview.
`production` prepares run mode and export. A failed build leaves the last
successful view available.

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

Remote server URLs must use HTTPS. HTTP is accepted for loopback hosts such as
`127.0.0.1` and `localhost`. Pass access tokens through
`MARIMO_STUDIO_ACCESS_TOKEN`, not through the URL.

## `marimo-studio view export`

```text
marimo-studio view export VIEW --output DIRECTORY [--target PATH] [--force] [--json]
```

Builds the production view and writes a static browser site. The result includes
the exact entry file. `--force` replaces an existing output directory after its
boundary has been validated.

Studio validates the destination before starting the production build. When the
directory already exists, review it before rerunning with `--force`.

The exported directory contains the notebook source.

## `marimo-studio view remove`

```text
marimo-studio view remove VIEW [--target PATH] [--yes] [--json]
```

Confirms before deleting the view and its source files. `--yes` is required for
machine-readable or non-interactive use. A configured notebook keeps at least
one view. The JSON result includes the updated `catalog_generation`.

## `marimo-studio validate`

```text
marimo-studio validate [VIEW] [--target PATH] [--level static|runtime|browser] [--server URL] [--browser-client ID] [--browser-timeout SECONDS] [--runtime-timeout SECONDS] [--json]
```

Validation grows with the selected level:

| Level     | Evidence                                                              |
| --------- | --------------------------------------------------------------------- |
| `static`  | Saved notebook, view source, configuration, and notebook-result names |
| `runtime` | Static evidence plus complete supervised notebook execution           |
| `browser` | Runtime evidence plus the selected rendered Studio view               |

Runtime validation executes notebook code with the current user's filesystem,
environment, and network authority. The child process owns lifecycle and
cleanup. It is not a security sandbox. Validate trusted notebooks.

The default level is `static`. Omit `VIEW` to validate every configured view at
the static or runtime level. Browser validation requires one view and a running
Studio server. Studio selects the connected tab when there is one. With several
tabs, pass the intended ID through `--browser-client` or
`MARIMO_STUDIO_BROWSER_CLIENT`. `--runtime-timeout` bounds supervised notebook
execution. `--browser-timeout` bounds the wait for current rendered evidence.

## Exit status

|  Exit | Meaning                                                           |
| ----: | ----------------------------------------------------------------- |
|   `0` | The requested operation completed                                 |
|   `1` | Validation or a named provider check failed                       |
|   `2` | Arguments or capability input are invalid                         |
|   `3` | Configuration, saved source, or a mutation precondition conflicts |
|   `4` | A notebook cell alias is invalid                                  |
|   `5` | A live Studio request failed                                      |
|   `6` | The installed Studio and marimo protocols disagree                |
|   `7` | The notebook environment cannot be prepared                       |
| `130` | The command was interrupted                                       |
