---
title: CLI
description: Inspect notebooks and create, edit, build, show, preflight, validate, export, rename, and remove Studio views, and set the default view.
---

# CLI

`marimo-studio` works with saved notebooks. Pass `--target` a notebook,
project directory, or `pyproject.toml`. When omitted, Studio resolves one
unambiguous configured notebook from the current directory and its parents.

Prefix a one-off command with `uvx`, [uv](https://docs.astral.sh/uv/)'s
temporary command runner, as in `uvx marimo-studio status`. Use
`uv run marimo-studio` inside a project that pins Studio.

Add `--json` when another program reads the result. Studio writes one JSON
result to stdout and JSON Lines diagnostic events to stderr. [Errors and
JSON](errors-and-json.md) defines the channel, event, and failure contracts.

::: warning Provider-backed commands execute trusted code
`doctor`, `starters`, and the commands under
[Provider environments](#provider-environments) can invoke installed providers.
Third-party provider code runs with the current user's filesystem, environment,
and network authority. Review provider packages before running these commands
or installing their launch requirements.
:::

## Provider environments

`status`, `view create`, `view inspect`, `view read`, `view write`, `view build`,
`view preflight`, `view export`, and `validate` read provider IDs from saved
`view.toml` files before provider code loads. Studio derives built-in
requirements such as `marimo-studio[deno]` from those IDs and reads third-party
provider requirements from the notebook's
[PEP 723](https://peps.python.org/pep-0723/) inline script metadata or project
`pyproject.toml`.

When the current process lacks a required Studio extra or third-party
provider, Studio reruns the command through `uv` in the notebook's declared
environment. `uv` may resolve and install packages before provider code loads,
so keep the `uv` executable available. A pixi workspace runs Studio in its own
activated environment instead, so declare Studio, its extras, and every
provider in the workspace.

A standalone notebook whose `# /// script` metadata has a `[tool.pixi]` table
supplies provider tools from its [pixi](https://pixi.prefix.dev/) script
environment. Commands that target the notebook run its builds, inspections,
revisions, and starter availability with commands such as `tectonic` from that
environment before `PATH`. They install the environment with
`pixi install --script`, which downloads its packages on first use and updates
an adjacent `<notebook>.pixi.lock` when one exists. The editor does the same
for every notebook that marimo runs with `--sandbox=pixi`, including one inside
a Python project, because marimo's sandbox ignores the project.

`validate --level runtime`, and `view preflight` or `view export` with
`--runtime zero-python`, execute notebook Python. When the notebook declares
dependencies, a Python version, or a project environment, these commands first
rerun through `uv` in that environment. `view export --runtime wasm` runs in the
current process because notebook Python executes later in the visitor's browser.

Reading or repairing `view.toml` uses Studio's provider-independent manifest
path in the current process, so the manifest stays available when its provider
is unavailable or its content needs repair.

## `marimo-studio doctor`

```text
marimo-studio doctor [PROVIDER] [--target PATH] [--json]
marimo-studio doctor --dependencies --target notebook.py [--json]
```

Lists installed view provider registrations, package versions, metadata,
availability, and starter IDs. The full inventory stays available when an
optional provider is unavailable. A named provider exits with status `1` when
it cannot load or reports unavailable. `doctor` does not inspect a view project
or run a provider build.

With `--target`, availability includes the tools that the notebook's pixi
metadata declares, as `starters --target` reports them:

```console
marimo-studio doctor marimo-studio/latex --target notebook.py
```

`--dependencies` compares active PEP 723 and owning project dependencies,
configured provider requirements, installed versions and extras, and resolution
of imports found in notebook source. Runtime checks use the combined project
and notebook dependency environment, including transitive requirements and
nested extras such as `marimo-studio[recommended]`. The owning project's
package is a valid import owner. The check reports drift even when both
declarations accept the installed version. Run it in the notebook's Python
environment:

```console
uv run --project . marimo-studio doctor --dependencies --target notebook.py --json
```

The report includes the interpreter, project path, declarations, installed
versions, import availability, and issues. Exit status is `1` when issues
exist. The check reads metadata and resolves top-level modules without
executing notebook cells, and it includes conditional imports. Dynamic imports,
package initialization failures, and direct-source provenance require runtime
validation or source review. Dependency groups and optional project extras are
not direct `project.dependencies` declarations.

## `marimo-studio starters`

```text
marimo-studio starters [--target PATH] [--json]
```

Lists installed starters for new view projects. Human output includes the
starter ID, summary, provider key, settings, availability, and recovery action.
Each setting line shows the key, its accepted values, its default, and its
help, such as `paper=a4|us-letter (default 'a4')`. `--target` reports
availability for one notebook, including the tools its pixi metadata declares.
JSON adds the title, `format`, `homepage`, the provider's `requirement`,
`settings`, the icon's SVG markup, the preview image's SHA-256 digest, and
`documents`, the starter's initial Source document plan. Use
`view create --dry-run` to inspect every file the selected starter and Studio
will write.

## `marimo-studio status`

```text
marimo-studio status [--target PATH] [--json]
```

Returns the notebook, active configuration source, default view, allowed
runtimes, cell aliases, named views, and exact `launch_requirements` for Studio
and configured provider distributions. `view_root` is the folder of authored
view projects, and `state_root` is the folder of their build state, as
[View projects](configuration.md#view-projects) describes. In a
[marimohub](../guide/marimohub.md) session, `persistence` reports which files
the hub saves when the session ends. It is `null` outside marimohub and before
the hub publishes the session. For an unconfigured notebook, the result
includes the command that creates its first view. `status` inspects every
configured view through its provider.

## `marimo-studio notebook inspect`

```text
marimo-studio notebook inspect [--target PATH] [--cell SELECTOR]...
  [--include-code] [--output-expressions] [--runtime] [--limit COUNT]
  [--context selected|upstream] [--runtime-timeout SECONDS] [--json]
```

Inspects saved cells, names, definitions, references, and dependency edges.
Repeat `--cell` to select a cell by name, stable ref, or zero-based index.

`--include-code` returns complete selected cell source. `--runtime` executes the
complete notebook and adds bounded
[media type](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/MIME_types)
outputs, such as HTML or an image, and JSON-compatible values.
`--runtime-timeout` bounds that execution. `--context upstream` adds every cell
that produces a selected cell's inputs.

## `marimo-studio notebook bind`

```text
marimo-studio notebook bind ALIAS --cell SELECTOR [--target PATH]
  [--dry-run] [--overwrite] [--json]
```

Gives one existing notebook cell a stable name for view source. `--dry-run`
reports the change. `--overwrite` replaces an existing alias.

## `marimo-studio view create`

```text
marimo-studio view create VIEW [--target PATH] [--starter ID] [--title TEXT]
    [--setting KEY=VALUE]... [--make-default] [--dry-run] [--json]
```

Creates one named view and rejects an existing name. The default starter,
`marimo-studio/vanilla:default`, creates editable `index.html` and `AGENTS.md`
documents, and Vanilla inspection also exposes directly referenced local CSS
and JavaScript files. `--starter` selects another installed starter.
`--dry-run` reports every planned write without committing it.

`--title` sets the title the starter writes into the view. Without it, Studio
makes one from the view name. `--setting` sets one of the starter's settings
and can repeat. Write `true` or `false` for a switch. `marimo-studio starters`
lists each starter's settings, their accepted values, and their defaults:

```console
marimo-studio view create report --target analysis.py \
  --starter marimo-studio/typst:default --title "Quarterly report" \
  --setting paper=us-letter --make-default
```

`--make-default` then serves the new view at the main route, as
`view default` does. A notebook's first view always becomes its default.

A completed creation returns exact `launch_requirements` in JSON and prints an
environment-aware launch command: `uv run` with `--no-sandbox` for project
notebooks, `pixi run` with `--no-sandbox` in a pixi workspace, and `uvx` with
`--sandbox` for standalone notebooks, or `--sandbox=pixi` when the notebook's
metadata has a `[tool.pixi]` table.

## `marimo-studio view default`

```text
marimo-studio view default VIEW [--target PATH] [--json]
```

Serves `VIEW` at the main route, `/`, by writing `default` in the Studio
configuration. The views and their project files stay unchanged. When the
configured `default` names a missing view, the command selects `VIEW` from the
view projects on disk and repairs the configuration.

The JSON result is the committed view catalog: the `view` the command changed,
the `views` with their generations in name order, the `default_view`, and the
`catalog_generation`. `view rename` and `view remove` report the same record.

## `marimo-studio view inspect`

```text
marimo-studio view inspect VIEW [--target PATH] [--json]
```

Inspects current filesystem content and returns the project `root`, ownership,
Source documents, file revisions, diagnostics, and development publication
state. `files_complete` reports whether source and build-input discovery
completed. `project_revision` identifies current inputs, and
`published_project_revision` identifies the retained artifact's inputs.
`latest_build` reports the latest attempt separately from the retained
successful `build`. [Identities and state](identities.md#build-freshness)
defines the freshness values.

## `marimo-studio view read`

```text
marimo-studio view read VIEW DOCUMENT [--target PATH] [--json]
```

Reads one authorized UTF-8 Source document and its current source revision.
Human output prints a path and revision header before the content. Use `--json`
before editing: the result includes `revision`, `catalog_generation`, and
`view_generation` from the same source read.

## `marimo-studio view write`

```text
marimo-studio view write VIEW DOCUMENT --expected-revision REVISION
  --catalog-generation GENERATION --view-generation GENERATION
  --from FILE|- [--target PATH] [--json]
```

Reads UTF-8 content from a file or stdin. The write succeeds when the source
revision, catalog generation, view generation, file identity, provider access
decision, and surrounding build inputs still match the preceding read. A
conflict preserves the current file. Read the document again, review its
content, and retry with the new preconditions. Both generation flags take the
64-character lowercase hexadecimal values that `view read --json` returns.

The document must appear in the current Source catalog with `access="edit"`.
`view.toml` remains available through Studio's provider-independent manifest
path. A write may change its `options`, and the view keeps its original
provider key.

Use `view remove` and `view create` for same-name replacement. [Identities and
state](identities.md#ownership-generations) defines the ownership checks that
reject a stale handle after replacement.

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

Builds and validates one view from an immutable snapshot of its declared build
inputs. The `development` profile serves Studio Preview, and `production`
serves run mode and static export. Each profile keeps its own latest attempt
and retained artifact.

A failed build keeps the last successful artifact for the selected profile
available. A successful build publishes the candidate only after output
validation and a final source and ownership check.

## `marimo-studio view hold`

```text
marimo-studio view hold VIEW --owner NAME [--ttl SECONDS] [--target PATH] [--json]
```

Delays replacement publication while source changes through any filesystem
tool or Studio. The hold applies across processes to that view incarnation and
keeps the current publication available. `--owner` names the editor. `--ttl`
defaults to 300 seconds and accepts values greater than zero and at most 3600
seconds. An active hold rejects another acquisition and reports its owner and
expiry.

Hold JSON contains `schema`, `view`, `token`, `owner`, `generation`,
`expires_at` in Unix seconds, and `status`. Keep `token` for `release`.

Hold publication while a multi-file edit passes through incomplete states:

```sh
marimo-studio view hold dashboard --target analysis.py \
  --owner source-refactor --ttl 300 --json > hold.json
```

Edit the files, inspect the result, then release the hold and build:

```sh
marimo-studio view inspect dashboard --target analysis.py
marimo-studio view release dashboard --target analysis.py \
  --token "$(jq -r .token hold.json)"
marimo-studio view build dashboard --target analysis.py
```

[jq](https://jqlang.org/manual/) extracts the token from the hold record. Keep
that record outside the view project's build inputs, and choose a `--ttl` that
covers the edit. A hold delays publication. It does not make filesystem writes
atomic or protect one external writer from another.

## `marimo-studio view release`

```text
marimo-studio view release VIEW --token TOKEN [--target PATH] [--json]
```

Release requires the matching token and is repeatable. Release JSON contains
`schema`, `view`, and `hold`, which is the released receipt or `null`.

Release or expiry lets the live editor reconcile current source and resume
publication. Source edits remain on disk. For offline edits, run `view inspect`
and `view build` after releasing.

## `marimo-studio view show`

```text
marimo-studio view show VIEW --server URL [--target PATH] [--browser-client ID] [--json]
```

Shows the view in a connected Studio tab. `MARIMO_STUDIO_SERVER_URL` can
replace `--server`. Set `MARIMO_STUDIO_ACCESS_TOKEN` when the server requires
authentication, and keep access tokens out of the URL. Remote server URLs must
use HTTPS. HTTP is accepted for loopback hosts such as `127.0.0.1` and
`localhost`.

Studio selects the connected tab automatically when there is one. When several
tabs are connected, the error lists their IDs. Pass one through
`--browser-client` or `MARIMO_STUDIO_BROWSER_CLIENT`.

The result includes `client_id`, `session_id`, `preview_url`, and
`frame_selector`. Use the selector in the selected Studio tab to target its
active preview document, including while its notebook outputs are preparing.
Successful activation commits the selected frame and its browser-authored
address. Before inspecting outputs or interacting, wait inside the frame for
`html[data-marimo-studio-state="ready"]`. Activation and readiness are separate
milestones so `show()` can return from code mode and marimo can process the
preview's kernel work. Refresh these fields with `view show` after a view,
runtime, or session change.

## `marimo-studio view preview`

```text
marimo-studio view preview VIEW
  --runtime server|wasm|zero-python
  --server URL [--exact] [--browser-client ID] [--target PATH] [--json]
```

Returns a URL for the view in a top-level browser document, as a JSON string
with `--json`. The URL keeps the origin and path of `--server`, including a
proxy path prefix. The CLI sends its own request to that server URL. When it
reaches the server through a local address, open the same path beneath the
browser's public root. The server must
expose the requested runtime, and edit-mode Python previews require an open
notebook session. `MARIMO_STUDIO_SERVER_URL` and `MARIMO_STUDIO_ACCESS_TOKEN`
work as in `view show` for the CLI request. The browser requires its own normal
server authentication.

On an edit-mode server, `--browser-client` selects the Studio tab that a
preview follows. A Python preview follows a tab when you name one. A Prepared
preview always follows a tab: without `--browser-client` it uses the only
connected tab and fails when none is connected. Run-mode previews follow no tab.

On an edit-mode server, an open preview follows the development build of each
source change, keeps its address, and reloads from that address after the
server restarts. On a run-mode server, reload after a production build.

`--exact` requires a current build for the served profile (development in edit
mode, production in run mode), then pins its presentation revision. Opening the
URL returns HTTP 409 when the revision differs or view source is unbuilt or
failed, even when the previous artifact is retained. The HTML attribute
`data-marimo-studio-revision` identifies the committed presentation. It differs
from the artifact revision that `view build` returns.

Wait for `html[data-marimo-studio-state="ready"]`, which covers the runtime
and mounted projections, before asserting content and behavior, inspecting
console and network failures, or capturing screenshots. When a previous
successful artifact stays visible after a failed build, check `view inspect`
for build freshness.

## `marimo-studio view preflight`

```text
marimo-studio view preflight VIEW [--target PATH]
  [--runtime zero-python|wasm] [--prepare-timeout SECONDS] [--json]
```

Builds the production artifact, prepares the selected static runtime, and
checks the staged browser files without publishing an output directory.
Prepared verifies each finite projection against every configured input state.
Browser reports projection support and validates the browser artifact without
executing notebook code in a browser.

The result includes every projection site, target, source location, runtime,
and portability status, plus the staged file count, inspected browser-source
count, local reference count, and source-located diagnostics. Human output is a
summary. Use `--json` for the complete report.

Preflight rejects fetched file URLs, machine-local paths, root-absolute URLs,
missing fetched assets, and unresolved local module paths. It warns when a
computed module import, URL constructor target, bare module specifier, parser
limitation, or size bound prevents complete static inspection. A warning keeps
the result successful and marks the remaining review boundary for the caller.
The command exits with status `1` when any error remains.

`--runtime zero-python` discovers projected outputs that retain Python
callbacks or fail during prepared-state capture. The diagnostic preserves the
`marimo-export` code and details. It identifies the projection when the
exporter provides enough output identity, and lists candidate projections
otherwise. `--prepare-timeout` behaves as in `view export`.

## `marimo-studio view export`

```text
marimo-studio view export VIEW --output DIRECTORY [--target PATH]
  [--runtime zero-python|wasm] [--prepare-timeout SECONDS] [--force] [--json]
```

Builds the production profile and writes a static site. `--runtime
zero-python`, the default, executes the notebook during export and packages
prepared outputs for the view's finite projection targets and configured input
states. `--runtime wasm` packages notebook source for execution through Pyodide
in the visitor's browser. `--prepare-timeout` bounds Prepared preparation and
defaults to 30 seconds. Studio rejects `--prepare-timeout` with
`--runtime wasm` before resolving the target or building the provider artifact.

The Prepared directory contains the production artifact, prepared result index
and assets, runtime configuration, notebook `public/` files, and a `.nojekyll`
marker. Python notebook and cell source stay on the machine that runs the
export, and the publication retains cell names, IDs, and code hashes as
provenance. The Browser directory also contains saved notebook source. Serve
either directory over HTTP. Browser package imports, remote data, fonts, maps,
and other view dependencies keep the network access the authored frontend
expects.

The result contains the runtime, exact entry file, file count, delivery
warnings, Prepared cache activity, and the complete static preflight report.
Authored hits and misses come directly from `marimo-export`'s observation of
marimo's native cell-cache decisions.

Studio writes progress to stderr for the production build, Prepared plan and
state preparation, bundle assembly, delivery preflight, and commit. With
`--json`, stderr carries [progress events](errors-and-json.md#progress-events)
and the terminal result stays on stdout.

Studio rejects a symlink destination, a filesystem root, the user's home
directory, and any destination that contains, equals, or sits within an export
source. Studio assembles and preflights the application in a `marimo-export`
`StagedDelivery`, and a failed preflight preserves the current destination.
`marimo-export` verifies the nested prepared export and complete directory
before committing it with destination change detection and rollback. `--force`
delegates replacement identity, rollback, and recovery to that staged delivery.

## `marimo-studio view rename`

```text
marimo-studio view rename VIEW NEW_NAME [--target PATH] [--json]
```

Moves the view project to `NEW_NAME` with its source, artifacts, and build
history. `NEW_NAME` follows the view name rules and must be free. A default
view stays the default under its new name. The project reads as `stale` until
its next build, which republishes it under `NEW_NAME`. An active publication
hold on `VIEW` blocks the rename until the hold is released or expires. The
JSON result is the [view catalog](#marimo-studio-view-default) with the new
name as `view`. A view that a running Studio server serves reports
`view-in-use`. See [Work in Studio](../guide/work-in-studio.md).

## `marimo-studio view remove`

```text
marimo-studio view remove VIEW [--target PATH] [--yes] [--json]
```

Confirms before deleting the view project. `--yes` is required for
machine-readable or non-interactive use. A configured notebook keeps at least
one view. The JSON result is the [view catalog](#marimo-studio-view-default)
with the removed name as `view`. A view that a running Studio server serves
reports `view-in-use`. See [Work in Studio](../guide/work-in-studio.md).

## `marimo-studio validate`

```text
marimo-studio validate [VIEW] [--target PATH] [--level static|runtime] [--runtime-timeout SECONDS] [--json]
```

Validation grows with the selected level:

| Level     | Evidence                                                                           |
| --------- | ---------------------------------------------------------------------------------- |
| `static`  | Saved notebook, configuration, view source, build contract, and projection targets |
| `runtime` | Static evidence plus one complete supervised notebook execution                    |

The default level is `static`. Omit `VIEW` to validate every configured view.
`--runtime-timeout` bounds supervised notebook execution. Use `view preview`
to check rendered behavior.

Runtime validation executes notebook code with the current user's filesystem,
environment, and network authority. The child process owns lifecycle and
cleanup. It is not a security sandbox. Validate trusted notebooks.

## Exit status

|  Exit | Meaning                                                        |
| ----: | -------------------------------------------------------------- |
|   `0` | The requested operation completed                              |
|   `1` | Validation, preflight, or a named provider check failed        |
|   `2` | Arguments or capability input are invalid                      |
|   `3` | Configuration, source, build, export, or mutation state failed |
|   `4` | A notebook cell alias is invalid                               |
|   `5` | A live Studio request failed                                   |
|   `6` | The installed Studio and marimo protocols disagree             |
|   `7` | The notebook environment cannot be prepared                    |
| `130` | The command was interrupted                                    |

[Errors and JSON](errors-and-json.md#expected-command-failures) defines the
error diagnostic that accompanies each failure.
