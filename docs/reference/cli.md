---
title: CLI
description: Inspect notebooks and create, edit, build, show, preflight, validate, export, and remove Studio views.
---

# CLI

`marimo-studio` works with saved notebooks. Pass `--target` a notebook,
project directory, or `pyproject.toml`. When omitted, Studio resolves one
unambiguous configured notebook from the current directory and its parents.

Prefix a one-off command with `uvx`, [uv](https://docs.astral.sh/uv/)'s
temporary command runner, as in `uvx marimo-studio status`. Use
`uv run marimo-studio` inside a project that pins Studio. Keep the `uv`
executable available for provider-backed commands. Studio uses it to re-enter
the notebook's declared Python environment when the current process lacks a
required Studio extra or third-party provider.

Add `--json` when another program will read the result. Studio writes one JSON
result to stdout and JSON Lines diagnostic events to stderr. [Errors and
JSON](errors-and-json.md) defines the channel, event, and failure contracts.

::: warning Provider-backed commands execute trusted code
Commands such as `doctor`, `starters`, `status`, `view create`, `view inspect`,
`view read`, `view write`, `view build`, `view preflight`, `view export`, and
`validate` can invoke installed providers. Third-party provider code runs with
the current user's filesystem, environment, and network authority. Review
provider packages before running these commands or installing their launch
requirements.
:::

## Provider environments

`status`, `view create`, `view inspect`, `view read`, `view write`, `view build`,
`view preflight`, `view export`, and `validate` read provider IDs from saved
`view.toml` files before provider code loads. Studio derives built-in requirements such as
`marimo-studio[deno]` from those IDs and reads third-party provider requirements
from the notebook's [PEP 723](https://peps.python.org/pep-0723/) inline script
metadata or project `pyproject.toml`.

When the current process does not satisfy those requirements, Studio reruns the
command through `uv`. `uv` may resolve and install packages before provider code
loads. A third-party key such as `acme-views/report` requires an active
`acme-views` dependency in the notebook or project.

`validate --level runtime`, and `view preflight` or `view export` with
`--runtime zero-python`, execute notebook Python. When the notebook declares
dependencies, a Python version, or a project environment, these commands rerun
through `uv` in that environment first. `view export --runtime wasm` runs in the
current process because notebook Python executes later in the visitor's browser.

Reading or repairing `view.toml` uses Studio's provider-independent manifest
path in the current process. This keeps the manifest available when its provider
is unavailable or its content needs repair.

## `marimo-studio doctor`

```text
marimo-studio doctor [PROVIDER] [--json]
marimo-studio doctor --dependencies --target notebook.py [--json]
```

Lists installed view provider registrations, package versions, metadata,
availability, and starter IDs. A named provider exits with status `1` when it
cannot load or reports unavailable. `doctor` does not inspect a view project or
run a provider build. The full inventory remains available when another
optional provider is unavailable.

`--dependencies` compares active PEP 723 and owning project dependencies,
configured provider requirements, installed versions and extras, and resolution
of imports found in notebook source. Runtime checks use the combined project
and notebook dependency environment, including transitive requirements and
nested extras such as `marimo-studio[recommended]`. The owning project's package
is a valid import owner. It reports drift even when both declarations
accept the installed version. Run it in the notebook's Python environment:

```console
uv run --project . marimo-studio doctor --dependencies --target notebook.py --json
```

The report includes the interpreter, project path, declarations, installed
versions, import availability, and issues. Exit status is `1` when issues exist.
This check reads metadata and resolves top-level modules without executing
notebook cells. Conditional imports are included. Dynamic imports, package
initialization failures, and direct-source provenance require runtime validation
or source review. Dependency groups and optional project extras are not direct
`project.dependencies` declarations.

## `marimo-studio starters`

```text
marimo-studio starters [--json]
```

Lists installed starters for new view projects. Human output includes the
starter ID, summary, provider key, availability, and recovery action. JSON adds
the title and `documents`, which is the starter's initial Source document plan.
Use `view create --dry-run` to inspect every file the selected starter and
Studio will write.

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
complete notebook and adds bounded
[media type](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/MIME_types)
outputs, such as HTML or an image, and JSON-compatible values.
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

Creates one named view and rejects an existing name. The default starter is
`marimo-studio/vanilla:default`. It creates editable `index.html` and
`AGENTS.md` documents. Vanilla inspection also exposes directly referenced
local CSS and JavaScript files. `--starter` selects another installed starter.
`--dry-run` reports every planned write without committing it.

A completed creation returns exact `launch_requirements` in JSON and prints an
environment-aware launch command. Project notebooks use `uv run` with
`--no-sandbox`; standalone notebooks use `uvx` with `--sandbox`. Install and run
requirements for reviewed providers.

## `marimo-studio view inspect`

```text
marimo-studio view inspect VIEW [--target PATH] [--json]
```

Inspects current filesystem content and returns the project `root`, ownership,
source documents, file revisions, diagnostics, and development publication
state. `files_complete` reports whether source and build-input discovery
completed. `project_revision` identifies current inputs, while
`published_project_revision` identifies the retained artifact's inputs.
`latest_build` reports the latest attempt separately from the retained
successful `build`. Open the `view preview` URL to inspect the rendered presentation.
[Identities and state](identities.md#build-freshness) defines the freshness
values.

## `marimo-studio view read`

```text
marimo-studio view read VIEW DOCUMENT [--target PATH] [--json]
```

Reads one authorized UTF-8 source document and its current source revision.

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
revision, catalog generation, view generation, file identity, provider access
decision, and surrounding build inputs still match the preceding read. A
conflict preserves the current file. Read the document again, review its
content, and retry with the new preconditions. Both generation flags accept the
64-character lowercase hexadecimal values returned by `view read --json`.

Source paths use forward slashes and start at the view project root. The
document must appear in the current Source catalog with `access="edit"`.
`view.toml` remains available
through Studio's provider-independent manifest path. A write may change its
`options`, but a view keeps its original provider key.

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
inputs.

| Profile       | Consumer                   | Publication state                                |
| ------------- | -------------------------- | ------------------------------------------------ |
| `development` | Studio Preview             | Independent latest attempt and retained artifact |
| `production`  | Run mode and static export | Independent latest attempt and retained artifact |

A failed build keeps the last successful artifact for the selected profile
available. A successful build publishes the candidate only after output
validation and a final source and ownership check.

## `marimo-studio view hold`

```text
marimo-studio view hold VIEW --owner NAME [--ttl SECONDS] [--target PATH] [--json]
```

`hold` delays replacement publication while source is edited through any
filesystem tool or Studio. The hold applies across processes to that view
incarnation. Existing published artifacts remain available. `--owner` names the
editor. `--ttl` defaults to 300 seconds and accepts values greater than zero
and at most 3600 seconds.

Keep the returned token for `release`. An active hold rejects another
acquisition and reports its owner and expiry. Hold JSON contains `schema`,
`view`, `token`, `owner`, `generation`, `expires_at` in Unix seconds, and `status`.

## `marimo-studio view release`

```text
marimo-studio view release VIEW --token TOKEN [--target PATH] [--json]
```

Release requires the matching token and is repeatable. Release JSON contains
`schema`, `view`, and `hold`, which is the released receipt or `null`.

Release or expiry permits the live editor to reconcile current source and
resume publication. Source edits remain on disk. For offline edits, run
`view inspect` and `view build` after releasing. See
[Manage view source](../guide/manage-source.md#coordinate-a-multi-file-change).

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

The result includes `client_id`, `session_id`, `preview_url`, and
`frame_selector`. Use the selector in the selected Studio tab to target its
active preview document, including while its notebook outputs are preparing.
Successful activation commits the selected frame and its browser-authored address.
Before inspecting outputs or interacting, wait inside the frame for
`html[data-marimo-studio-state="ready"]`. Keeping these milestones separate lets
`show()` return from code mode so Marimo can process the preview's kernel work.
Refresh these fields with `view show` after a view, runtime, or session change.

Remote server URLs must use HTTPS. HTTP is accepted for loopback hosts such as
`127.0.0.1` and `localhost`. Pass access tokens through
`MARIMO_STUDIO_ACCESS_TOKEN`, not through the URL.

## `marimo-studio view preview`

```text
marimo-studio view preview VIEW
  --runtime server|wasm|zero-python
  --server URL [--exact] [--target PATH] [--json]
```

Returns a URL string for the view in a top-level browser document. `--json`
returns a JSON string. Open it with your preferred browser tool. The server
must expose the requested runtime. Edit-mode Server previews require an open
notebook session. Use `MARIMO_STUDIO_SERVER_URL` to supply the server URL and
`MARIMO_STUDIO_ACCESS_TOKEN` to authenticate the request when needed. The browser
requires its own normal server authentication.

Use the stable URL while iterating and reload after builds. `--exact` requires
a current build for the served profile (development in edit mode, production
in run mode), then pins its presentation revision. Opening it returns HTTP 409
when the revision differs or view source is unbuilt or failed, even if the
previous artifact is retained. The HTML attribute `data-marimo-studio-revision`
identifies the committed presentation. It differs from the artifact revision returned by
`view build`.

Wait for `html[data-marimo-studio-state="ready"]`, then assert application
content and behavior, inspect console and network failures, and capture
screenshots. Studio readiness covers the runtime and mounted projections.
Check `view inspect` for build freshness when a previous successful artifact
remains visible after a failed build.

## `marimo-studio view preflight`

```text
marimo-studio view preflight VIEW [--target PATH]
  [--runtime zero-python|wasm] [--prepare-timeout SECONDS] [--json]
```

Builds the production artifact, prepares the selected static runtime, and
checks the staged browser files without publishing an output directory.
Zero-Python verifies each finite projection against every configured input
state. WebAssembly reports projection support and validates the browser
artifact without executing notebook code in a browser.

The result includes every projection site, target, source location, runtime,
and portability status. It also reports the staged file count, inspected
browser-source count, local reference count, and source-located diagnostics.

Preflight rejects fetched file URLs, machine-local paths, root-absolute URLs,
missing fetched assets, and unresolved local module paths. It warns when a
computed module import, URL constructor target, bare module specifier, parser
limitation, or size bound prevents complete static inspection. A warning
preserves a successful result and gives the caller the remaining review
boundary.

Use `--runtime zero-python` to discover projected outputs that retain Python
callbacks or fail during prepared-state capture. The diagnostic preserves the
`marimo-export` code and details, identifies the projection when the exporter
provides enough output identity, and lists candidate projections otherwise.

`--prepare-timeout` has the same Zero-Python behavior as `view export`.

## `marimo-studio view export`

```text
marimo-studio view export VIEW --output DIRECTORY [--target PATH]
  [--runtime zero-python|wasm] [--prepare-timeout SECONDS] [--force] [--json]
```

Builds the production profile and writes a static site. `--runtime zero-python`
is the default. It executes the notebook during export and packages prepared
outputs for the view's finite projection targets and configured input states.
`--runtime wasm` packages notebook source for execution through Pyodide in the
visitor's browser. `--prepare-timeout` bounds Zero-Python preparation and
defaults to 30 seconds. Studio rejects `--prepare-timeout` with
`--runtime wasm` before resolving the target or building the provider artifact.

Zero-Python keeps Python notebook and cell source on the build machine. Its
publication retains cell names, IDs, and code hashes as provenance. Projected
outputs and files under the notebook's `public/` directory are included in the
static directory.

The result contains the runtime, exact entry file, file count, delivery
warnings, and Zero-Python cache activity. It also contains the complete static
preflight report. Authored hits and misses come directly from marimo-export's
observation of Marimo's native cell-cache decisions. `--force` delegates
replacement identity, rollback, and recovery to marimo-export's staged
application delivery.

Export progress is written to stderr. It covers the production build,
Zero-Python plan and state preparation, bundle assembly, delivery preflight,
and commit. `--json` keeps the terminal result on stdout and writes schema 1
JSON Lines progress events to stderr. Each progress record includes the view,
runtime, owning source, and nested event. Events owned by marimo-export retain
its state counts, cache activity, elapsed time, and message unchanged. Callers
can stream or discard stderr independently of the result.

Studio rejects a symlink destination, a filesystem root, the user's home
directory, and any destination that contains, equals, or sits within an export
source. Studio assembles and preflights the application in a marimo-export
`StagedDelivery`. A failed preflight preserves the current destination.
Marimo-export verifies the nested prepared export and complete directory before
committing it with destination change detection and rollback.

The Zero-Python directory contains the production artifact, prepared result
index and assets, runtime configuration, notebook `public/` files, and a
`.nojekyll` marker. The WebAssembly directory also contains saved notebook
source. Serve either directory over HTTP. Browser package imports, remote data,
fonts, maps, and other view dependencies keep the network access expected by
the authored frontend.

## `marimo-studio view remove`

```text
marimo-studio view remove VIEW [--target PATH] [--yes] [--json]
```

Confirms before deleting the view project. `--yes` is required for
machine-readable or non-interactive use. A configured notebook keeps at least
one view. The JSON result includes the updated `catalog_generation`.

## `marimo-studio validate`

```text
marimo-studio validate [VIEW] [--target PATH] [--level static|runtime] [--runtime-timeout SECONDS] [--json]
```

Validation grows with the selected level:

| Level     | Evidence                                                              |
| --------- | --------------------------------------------------------------------- |
| `static`  | Saved notebook, view source, configuration, and notebook-result names |
| `runtime` | Static evidence plus complete supervised notebook execution           |

Runtime validation executes notebook code with the current user's filesystem,
environment, and network authority. The child process owns lifecycle and
cleanup. It is not a security sandbox. Validate trusted notebooks.

The default level is `static`. Omit `VIEW` to validate every configured view.
`--runtime-timeout` bounds supervised notebook execution. Use `view preview`
and your browser's assertions to check rendered behavior.

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

See [Errors and JSON](errors-and-json.md#expected-command-failures) for the
machine-readable error event associated with each category.
