---
title: Python API
description: Inspect notebooks, author views, verify the current Studio tab, and serve a configured notebook.
---

# Python API

Use `marimo_studio.authoring` for a saved notebook on disk. Use
`marimo_studio.agent` inside
[marimo code mode](https://docs.marimo.io/guides/editor_features/tools/#code-mode),
which runs a coding agent's Python inside the live notebook kernel, when an
operation needs the current Studio tab. Public records are frozen dataclasses
whose `to_dict()` methods produce the schema of `marimo-studio --json`.

## `marimo_studio.authoring`

### `open_workspace`

```python
from marimo_studio.authoring import open_workspace

workspace = open_workspace("analysis.py")
```

```text
open_workspace(notebook: str | Path) -> Workspace
```

Resolves the path and returns a workspace handle. Raises `ConfigurationError`
when the resolved path is not a regular file. Each operation loads and
validates the notebook and Studio configuration it needs.

### `Workspace`

`Workspace` binds authoring operations to one notebook path.

```text
await workspace.status() -> StudioOverview
await workspace.inspect_notebook(
    *,
    runtime: bool = False,
    include_code: bool = False,
    selectors: tuple[CellSelector, ...] = (),
    output_expressions: bool = False,
    context: Literal["selected", "upstream"] = "selected",
    limit: int | None = None,
    runtime_timeout: float = 60.0,
) -> InspectionResult
await workspace.starters() -> tuple[Starter, ...]
await workspace.create_view(name, *, starter=None) -> View
workspace.view(name) -> View
await workspace.bind(alias, cell, *, overwrite=False) -> BindingResult
await workspace.validate(
    *,
    level: Literal["static", "runtime"] = "static",
    view: str | None = None,
    runtime_timeout: float = 60.0,
) -> ValidationReport
```

Static inspection never executes notebook code. Runtime inspection and runtime
validation execute the complete notebook in an owned child process, which
inherits the interpreter environment, current directory, OS user permissions,
filesystem access, and network access. The process boundary terminates the
child process tree after cancellation or a timeout. It bounds the lifecycle
and is not a security sandbox, so run trusted notebook code only.

`context="upstream"` with one or more selectors includes every cell that
produces their inputs.

`create_view()` raises `ViewExistsError` when the name already has a view.
`view()` reads the current catalog and returns a handle bound to that workspace
and view incarnation. `create_view()` and `bind()` raise
`WorkspaceGenerationConflictError` for a replaced workspace. Open a new
workspace before retrying.

### `StudioOverview`

Returned by `Workspace.status()`. Describes the configuration source, notebook,
view root, build state root, runtime choices, cell aliases, and configured
views. `view_root` holds the authored view projects, and `state_root` holds
their replaceable build state. `generation` identifies the returned catalog and
changes when its configuration or view incarnations change.

In a [marimohub](../guide/marimohub.md) session, `persistence` reports which
files the hub saves when the session ends: `"workspace"` saves workspace files,
`"source"` saves the notebook and its dependencies, and `"none"` saves nothing.
It is `None` outside marimohub and before the hub publishes the session.

`launch_requirements` lists the exact Studio requirement with configured
provider extras and the exact installed third-party provider distributions
needed to reopen the workspace in another `uv` environment. Studio needs the
`uv` executable to prepare or re-enter that environment.

### `ViewOverview`

Identifies one configured view, its project path, provider, Source document
paths, default status, generation, and current artifact revision.
`View.inspect()` reads each document's access mode.

### `InspectionResult`

Contains the selected static notebook cells and optional runtime outputs and
values returned by `Workspace.inspect_notebook()`.

### `RuntimeProbe`

Contains runtime cell state, serialized values, and rendered outputs for one
completed runtime inspection.

### `RuntimeCell`

Records one selected cell's terminal status, output summaries, and runtime
errors.

### `RuntimeOutput`

Summarizes one cell output by channel,
[media type](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/MIME_types),
which identifies formats such as HTML or an image, and whether its payload is
empty.

### `ValueReadResult`

Maps requested value selectors to serialized values or `ValueReadError`
records.

### `ValueReadError`

Provides the stable code and message for one value that the runtime could not
serialize or return.

### `OutputRenderResult`

Maps requested output selectors to `RenderedOutput` or `ValueReadError`
records.

### `RenderedOutput`

Contains one rendered output's owner cell, MIME type, payload, timestamp, and
UI object reset identifiers.

### `Starter`

Describes one installed starter through `id`, `title`, `summary`, `provider`,
the initial Source document plan in `documents`, and current `availability`.
`marimo-studio view create VIEW --target PATH --dry-run` lists the complete
file set before creation. `Workspace.create_view()` creates the view directly.

### `BindingResult`

Identifies the alias, selected notebook cell, configuration path, and previous
binding returned by `Workspace.bind()`. `catalog_generation` identifies the
post-commit catalog captured by the owning workspace.

### `View`

`View` binds view operations to one workspace and name.
`catalog_generation` and `generation` identify the catalog and view incarnation
that the handle observed.

Successful `Workspace.bind()`, `Workspace.create_view()`, `View.make_default()`,
`View.rename()`, and `View.remove()` advance the owning `Workspace`. Existing
`View` handles stay bound to their original generations. Use the handle that
`make_default()` or `rename()` returns, or reacquire handles with
`workspace.view(name)` after a catalog mutation.

Replace a same-name view with Studio's remove and create operations. A direct
filesystem delete and recreation between observations that reuses
`(device, inode, mode)`, including exact-byte recreation, falls outside the
mutation-ownership contract.

```text
await view.inspect() -> ViewInspection
await view.read(path) -> ViewDocument
await view.write(path, content, *, expected_revision) -> ViewDocument
await view.build(*, profile="development") -> ViewBuild
await view.preview_url(
    *,
    runtime: str,
    exact: bool = False,
    server: str | None = None,
    access_token: str = "",
    browser_client: str = "",
) -> str
await view.hold_publication(*, owner: str, ttl: float = 300.0) -> PublicationHold
await view.release_publication(token: str) -> PublicationHold | None
await view.validate(
    *,
    level: Literal["static", "runtime"] = "static",
    runtime_timeout: float = 60.0,
) -> ValidationReport
await view.export(
    output,
    *,
    runtime: StaticRuntime = "zero-python",
    force: bool = False,
    prepare_timeout: float | None = None,
    progress: Callable[[StaticExportProgress], None] | None = None,
) -> StaticExportResult
await view.preflight(
    *,
    runtime: StaticRuntime = "zero-python",
    prepare_timeout: float | None = None,
    progress: Callable[[StaticExportProgress], None] | None = None,
) -> StaticPreflightReport
await view.make_default() -> View
await view.rename(new_name: str) -> View
await view.remove() -> ViewCatalog
```

`make_default()` serves the view at the main route (`/`) and returns a handle
bound to the committed catalog. Selecting the current default leaves the
catalog unchanged.

`rename(new_name)` moves the view project with its source, artifacts, and build
history, and returns the handle for the new name. A default view stays the
default. The project reads as `stale` until its next `build()` republishes it
under the new name. Handles bound to the old name raise
`ViewGenerationConflictError` from view operations such as `inspect()` and
`build()`. `rename()` raises `ViewExistsError` for a taken name, including the
view's own name, `InvalidViewNameError` for a name outside the view name rules,
`PublicationHeldError` while a publication hold is active, and
`ViewRenameError` when the project folder cannot move. After each of these
errors the view keeps its old name.

`remove()` deletes the view project and returns the remaining views as a
`ViewCatalog`. It raises `LastViewError` for the only view. `ViewDeletionError`
reports an incomplete filesystem cleanup and exposes the cleanup path through
`diagnostic_details()`.

`rename()` and `remove()` raise `ViewInUseError` while another process holds
an artifact lease for the view. Its `processes` detail lists the holding
process IDs. `WorkspaceMutationError` reports a change that did not finish
cleanly, so open a new `Workspace` before continuing. When its `recovery`
names a renamed project folder, the view reloads under the new name, and
`marimo-studio view default VIEW` repairs a default that still names the old
one.

A catalog change after the handle was acquired, including a same-name
replacement, makes `make_default()`, `rename()`, and `remove()` raise
`WorkspaceGenerationConflictError`. Open a new `Workspace` and acquire the
view again.

`inspect()` reads current filesystem state. Edit source with filesystem tools
or `write()`. Provider inspection owns document access and build-input
discovery. See [Work in Studio](../guide/work-in-studio.md) for multi-file
edits and recovery.

`write()` checks the expected source revision under the Studio editor's lock.
A stale revision raises `SourceConflictError` and preserves the newer file.

`show()`, `write()`, `build()`, `validate()`, `preflight()`, and `export()`
verify the handle's catalog and view generation. A same-name replacement raises
`ViewGenerationConflictError` before browser activation, source writes, or
artifact publication. `export()` checks again before replacing its destination,
including with `force=True`.

`preflight()` builds, prepares, and inspects the complete static bundle in a
temporary directory and returns before publishing a caller-owned destination.
`export()` runs the same preflight before it writes one static runtime.
`runtime="zero-python"` prepares the configured notebook states.
`runtime="wasm"` packages notebook source for execution through Pyodide in each
visitor's browser. `prepare_timeout` bounds Prepared preparation and defaults
to 30 seconds. With `runtime="wasm"`, `prepare_timeout` raises `ValueError`
before Studio loads the workspace or builds the provider artifact.

`progress` receives ordered `StaticExportProgress` records from the synchronous
export worker. Each record wraps either a `marimo_export.ProgressEvent` or a
Studio-owned `StaticExportStep`. Keep callbacks fast and thread-safe. An
exception from the callback cancels static destination publication.

`build()` returns the artifact revision of the selected development or
production build. The profiles keep independent publications. A failed build
leaves the last successful artifact for that profile available.

#### `preview_url()`

Returns the running view's URL for a top-level browser document. Choose
`runtime="server"`, `"wasm"`, or `"zero-python"` explicitly, and the server
must expose that runtime. Saved-workspace callers supply `server`, and the URL
keeps its origin and path, including a proxy path prefix. A live code-mode view
infers the local server address that marimo uses for callbacks and follows the
attached Studio tab. Behind a proxy, open the same path beneath the browser's
public root. In a [marimohub](../guide/marimohub.md) session, a code-mode URL
uses the hub's public address for the sandbox. `access_token` authenticates the
server request. On an edit-mode server, `browser_client` selects the Studio tab
that a Python or Prepared preview follows. Both require `server`. The browser
still needs the server's normal authentication.

The default URL follows the current presentation when opened or reloaded.
`exact=True` requires current source to be built for the served profile
(development in edit mode, production in run mode) and pins its presentation
revision. Opening that URL returns HTTP 409 when the revision differs or view
source is unbuilt or failed, even when the previous artifact is retained. The
method returns an address and leaves browser tabs untouched.

Finish code-mode execution before waiting for output in the browser, then
follow [Presentation readiness](projections.md#presentation-readiness).
`inspect()` reports source and build freshness.

### `View.hold_publication` and `View.release_publication`

```text
await view.hold_publication(*, owner: str, ttl: float = 300.0) -> PublicationHold
await view.release_publication(token: str) -> PublicationHold | None
```

`hold_publication()` delays replacement publication across processes while
source editing stays available. Existing published artifacts can be reused.
`owner` identifies the editor and has 1 to 256 characters, at least one of them
non-whitespace. `ttl` is a finite number of seconds greater than zero and at
most 3600. Invalid arguments raise `ValueError`. An active hold raises
`PublicationHeldError` with its owner and expiry.

Keep the returned token. In a later execution,
`(await view.inspect()).publication_hold` returns the current hold with its
token, or `None` when the view has no hold record. `release_publication()`
releases the matching hold and returns its receipt, and repeating the release
returns the same receipt. It returns `None` when the view has no hold record. A
mismatched token raises `ConfigurationError`. Both methods enforce the handle's
view generation and stay available when the manifest needs repair.

Release or expiry lets the live editor reconcile and publish current source.
For an offline workflow, call `build()` after release. Source changes stay on
disk after release, expiry, or editing-process exit.

### `PublicationHold`

Contains `token`, `owner`, view `generation`, `expires_at` as Unix seconds, and
`released`. The computed `status` is `active`, `expired`, or `released`. The
computed `expiry` renders `expires_at` as UTC text, such as
`2026-09-30 14:32:45 UTC`. `to_dict()` includes `status` with the token, owner,
generation, and expiry.

### `ViewBuild`

```text
ViewBuild(
    view: str,
    profile: Literal["development", "production"],
    revision: str,
    issues: tuple[ProjectDiagnostic, ...],
)
```

Describes one successful view build. `revision` identifies the complete browser
output.

### `ViewDocument`

Contains one authorized document's path, language, access mode, UTF-8 content,
and current revision.

### `ViewInspection`

Contains current filesystem and development publication evidence:

| Field                                              | Meaning                                                                                         |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `view`, `root`, `generation`, `catalog_generation` | View name, project root, and observed ownership.                                                |
| `provider`, `documents`, `diagnostics`             | Provider, authorized Source catalog, and source-located repair diagnostics.                     |
| `project_revision`                                 | Revision of observed build inputs, or `None` when unavailable. Interpret with `files_complete`. |
| `published_project_revision`                       | Source revision behind the retained development artifact, or `None` when unbuilt.               |
| `freshness`, `build`                               | Development freshness and retained successful artifact.                                         |
| `latest_build`                                     | Latest development attempt, including its `phase` and diagnostics.                              |
| `files`, `files_complete`                          | Observed source and build-input inventory and whether discovery completed.                      |
| `publication_hold`                                 | Current, expired, or released hold receipt, or `None`.                                          |

A provider or manifest failure returns diagnostics and an incomplete inventory.
When `view.toml` needs repair, `provider` is `None` and publication fields
describe stored build receipts. Repair the manifest through its path, then
inspect again to verify the provider and artifact. Artifact metadata describes
disk publication, and browser assertions check one rendered presentation.
[Identities and state](identities.md#build-freshness) lists freshness values.

```text
inspection.changes_since(previous: ViewInspection) -> ViewSourceChanges
```

Compares file revisions from two complete inventories. Raises `ValueError`
when either inventory is incomplete or the root, view, or generation differs.

### `ViewSourceFile`

Contains a project-relative `path` and content `revision`. A `None` revision
records an expected file that is missing.

### `ViewSourceChanges`

Contains `added`, `modified`, and `deleted` path tuples. `to_dict()` serializes
each tuple as a list of forward-slash paths.

### `StudioDiagnostic`

Names one source or build issue with a stable code, severity, repair hint, and
optional source location.

### `StaticRuntime`

`Literal["zero-python", "wasm"]`. Selects the single notebook runtime written
into a static export.

### `StaticExportResult`

Contains `notebook`, `view`, selected `runtime`, provider artifact `document`,
`cache_activity`, `preflight`, and `marimo-export`'s `DeliveryResult`. The
`output`, `files`, and `warnings` properties expose the committed delivery.
A Prepared result carries `marimo-export`'s authored and projection cache
dispositions, and a Browser result sets `cache_activity` to `None`. The
`entrypoint` property resolves `output / document`. `to_dict()` emits the
flattened output path, file count, warnings, and resolved entrypoint.

### `StaticExportProgress`

Contains the selected `view`, `runtime`, event `source`, and nested `event`.
`source="marimo-export"` preserves an upstream `ProgressEvent` unchanged.
`source="marimo-studio"` carries a `StaticExportStep` for production build,
bundle assembly, preflight, or commit. The returned result marks export
completion.

### `StaticExportStep`

Contains a Studio-owned `kind` and optional `completed`, `total`,
`elapsed_seconds`, and `message` fields. Import `ProgressEvent` from
`marimo_export` to distinguish preparation events from Studio steps.

### `StaticExportEvent`

`ProgressEvent | StaticExportStep`. Inspect `StaticExportProgress.source` or
the concrete `event` type when rendering owner-specific fields.

### `StaticPreflightReport`

Contains the `view`, `runtime`, entry `document`, staged `files`, eligible
`browser_files`, `inspected_files`, `references`, `projections`, and `issues`.
`ok` is false when an issue has error severity. `to_dict()` returns the schema 1
machine record used by the CLI and `StaticExportResult`.

### `ProjectionPortability`

Identifies one projection `site_id`, kind, optional target, static runtime,
source location, reason, and status:

| Status                  | Meaning                                                               |
| ----------------------- | --------------------------------------------------------------------- |
| `supported`             | The runtime accepts the projection model without prepared execution.  |
| `verification-required` | Prepared still needs to capture the target's configured states.       |
| `verified`              | Prepared captured the target through the completed preflight.         |
| `incompatible`          | The selected runtime cannot represent the authored projection target. |

### `StaticPreflightIssue`

Names one source-located delivery diagnostic with `code`, `severity`,
`message`, optional `reference`, and `hint`. Errors stop export before the
destination changes. Warnings identify browser dependencies for the caller to
review.

### `ViewCatalog`

Records the views of a notebook after a catalog change, as returned by
`View.remove()`. `views` maps each view name to its view generation in name
order, `default_view` names the view at `/`, and `catalog_generation`
identifies the committed catalog that the owning workspace captured.

### `ValidationReport`

```text
ValidationReport(
    notebook: Path,
    view: str | None,
    level: Literal["static", "runtime"],
    ok: bool,
    issues: tuple[ValidationIssue, ...],
    evidence: Mapping[str, object],
)
```

`ok` answers whether the requested validation completed against one coherent
source and runtime state.

### `ValidationIssue`

```text
ValidationIssue(
    stage: Literal["validation", "static", "runtime"],
    severity: Literal["warning", "error"],
    code: str,
    message: str,
    advice: str,
    view: str | None = None,
    target: str | None = None,
    source: dict[str, object] | None = None,
)
```

Names one problem and the next repair action. Errors make `ValidationReport.ok`
false. Warnings are left to task-specific judgment.

### `doctor`

```text
await doctor(provider: str | None = None) -> ProviderReport
```

Returns installed view provider registrations, package versions, availability,
and starter IDs. Pass a provider key to select one registration.

### `ProviderReport`

Contains the provider registration records returned by `doctor()`. Each record
includes its derived key, distribution, installed version, load state,
availability, and starter IDs.

### `ProviderDiagnostic`

Describes one installed provider registration, including its package identity,
load error, provider metadata, availability, and discovered starter IDs.

## `marimo_studio.agent`

`import marimo_studio` exposes this module as `marimo_studio.agent` and loads
it on first attribute access. Import `marimo_studio.agent` directly for typed
editor completion.

### Installed briefing

```python
import agent_plugins as ap

print(ap.read("marimo-studio"))
```

Returns the installed core skill with its package identity and resource paths.
`help(marimo_studio.agent)` includes the same briefing and Python API help.
Reading instructions leaves the workspace and current view unchanged.

### `skill`

```text
skill() -> agent_plugins.Skill
```

Returns Studio's packaged `marimo-studio` skill. Read its body or a task-specific
reference:

```python
import marimo_studio

skill = marimo_studio.agent.skill()
print(skill.body)
print(skill.file("references/verification.md").read_text())
```

Raises `AgentPluginError` when the installed plugin has no usable Studio skill.

### `plugin`

```text
plugin() -> agent_plugins.Plugin
```

Returns the complete [Agent Plugin](https://github.com/peter-gy/agent-plugins)
bundled with the installed Studio version:

```python
import marimo_studio

resources = marimo_studio.agent.plugin()
print(resources.tree())
```

Raises `AgentPluginError` when the installed distribution has no usable plugin.

### `current_workspace`

```python
import marimo_studio

workspace = marimo_studio.agent.current_workspace()
```

```text
current_workspace() -> Workspace
```

Returns the live `Workspace` for the current code-mode notebook and Studio tab.
Call it once in each code-mode execution.

### `Workspace`

The live workspace supports the saved-notebook operations of
`marimo_studio.authoring`. `inspect_notebook()` reads saved source, and runtime
inspection executes a separate process, so neither returns the live kernel
globals. Workspace-wide validation stays static or isolated runtime
validation.

The live API returns the same `PublicationHold`, `ViewInspection`,
`ViewSourceFile`, `ViewSourceChanges`, `ValidationReport`, and
`ValidationIssue` records as saved-workspace authoring. `ViewInspection`
source evidence describes saved files.

### `View`

The live view supports `preview_url()` with the current server inferred from
code mode, and activation in the user's Studio tab:

```text
await view.show() -> ShowResult
```

`show()` selects the view in the current Studio tab. Run it in a separate
code-mode execution so the notebook can finish rendering. For direct page
inspection, open the URL from `preview_url(runtime="server")` in a browser
tool.

The attached Studio server runs `rename()` and `remove()` and first releases
the artifacts it serves for the view. A failure raises `AgentRequestError`
whose `code` names the error, such as `view-exists` or `view-in-use`, and whose
`details` carry the diagnostic details. Call `show()` on the handle that
`rename()` returns to display the renamed view in the Studio tab.

### `ShowResult`

```text
ShowResult(
    notebook: Path,
    view: str,
    generation: int,
    session_id: str,
    client_id: str,
    *,
    preview_url: str,
    frame_selector: str,
)
```

Confirms that the intended Studio tab accepted the view selection.
`generation` is the tab's monotonically increasing activation generation,
distinct from the 64-character view generation used for mutation ownership.
`preview_url` and `frame_selector` address the activated document in that
Studio tab. `View.preview_url()` returns a separate top-level presentation URL.

## `marimo_studio`

### `agent`

The agent module is available after importing Studio:

```python
import marimo_studio

print(marimo_studio.agent.skill().body)
```

See [`marimo_studio.agent`](#marimo-studio-agent) for installed instructions and
the notebook-bound authoring API.

### `inspect_notebook`

```python
from marimo_studio import inspect_notebook

notebook = inspect_notebook("analysis.py", include_code=True)
```

```text
inspect_notebook(path: str | Path, *, include_code: bool = False) -> NotebookSpec
```

Compiles the saved notebook without executing it and returns its cells, source
spans, definitions, references, and dependency relationships.

### `create_asgi_app`

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("analysis.py")
```

```text
create_asgi_app(notebook: str | Path) -> ASGIApp
```

Returns a marimo run-mode [ASGI](https://asgi.readthedocs.io/en/latest/)
application that serves the notebook's default and named views. ASGI is the
standard interface between asynchronous Python web applications and servers.
The application lifespan opens Studio services and, at shutdown, closes its
notebook sessions and background tasks, so forward the lifespan through the
ASGI server.

marimo owns authentication and supplies read and edit scopes to Studio routes.
The hosting stack owns TLS, proxy headers, process supervision, network
exposure, and resource limits. See
[Compatibility and support](compatibility.md#deployment-boundary).

`marimo_studio.asgi:app` reads the notebook path from
`MARIMO_STUDIO_NOTEBOOK` for application servers:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app --host 127.0.0.1 --port 8000
```

### `STUDIO_RESULT_SELECTOR`

CSS selector for connected cell, output, and value hosts, parents containing
hidden value hosts, custom regions annotated with `data-marimo-lens-inputs`,
and authored regions marked with `data-marimo-lens-target`. Pass it to
[Lens](https://marimo-team.github.io/marimo-lens/) to collect feedback from
native projections and custom rendered regions:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
```

Render `studio_lens` through `<marimo-output value="studio_lens">` in the view.
Lens reads resolved producer and value-selector metadata from the linked hosts.
Studio publishes a document-local `data-marimo-lens-scope` on `#app-shell` so
unannotated HTML can receive feedback. Its value is a CSS selector for
preferred grouping regions, with the nearest block as a fallback, and a view's
source can set its own. `data-marimo-lens-target` makes an explicit parent take
precedence over smaller targets inside it. Stable region IDs preserve feedback
across rebuilds. See
[custom JavaScript rendering](projections.md#trace-custom-javascript-rendering)
for the authoring contract.

### `ASGIApp`

Protocol for the asynchronous `scope`, `receive`, and `send` callable returned
by `create_asgi_app()`.

### `NotebookSpec`

Static notebook inventory returned by `inspect_notebook()`. It provides
`by_ref()`, `named_cells()`, and `to_dict()`.

## Errors

Catch `MarimoStudioError` for expected configuration, source, build, runtime,
and live-browser failures:

```python
from marimo_studio.errors import MarimoStudioError

try:
    await view.build()
except MarimoStudioError as error:
    print(error.code, error)
```

Every expected error exposes a stable `code`, CLI `exit_code`, HTTP
`status_code`, retry classification, public hint, and structured diagnostic
details. Catch a narrower class such as `SourceConflictError`,
`ViewNotFoundError`, or `RuntimeTimeoutError` when the recovery differs.
[Errors and JSON](errors-and-json.md#public-error-classes) lists every class,
code, status, and recovery.

## Public records

These tables list fields that have related names across command and Python
surfaces. `NotebookSpec` and `InspectionResult` document their nested notebook
records.

### Workspace and view records

| Record               | Fields                                                                                                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `StudioOverview`     | `notebook`, `state`, `generation`, `config_path`, `config_source`, `view_root`, `state_root`, `default_view`, `default_runtime`, `runtimes`, `bindings`, `views`, `launch_requirements`, `persistence` |
| `ViewOverview`       | `name`, `generation`, `path`, `default`, `provider`, `documents`, `artifact_revision`                                                                                                                  |
| `Starter`            | `id`, `title`, `summary`, `provider`, `documents`, `availability`                                                                                                                                      |
| `BindingResult`      | `alias`, `cell`, `config_path`, `catalog_generation`, `dry_run`, `previous_ref`                                                                                                                        |
| `ViewDocument`       | `path`, `language`, `access`, `content`, `revision`                                                                                                                                                    |
| `ViewInspection`     | `view`, `provider`, `documents`, `diagnostics`, `freshness`, `build`                                                                                                                                   |
| `ViewBuild`          | `view`, `profile`, `revision`, `issues`                                                                                                                                                                |
| `ViewCatalog`        | `notebook`, `default_view`, `views`, `catalog_generation`                                                                                                                                              |
| `StaticExportResult` | `notebook`, `view`, `runtime`, `document`, `cache_activity`, `preflight`, `delivery` and computed `output`, `files`, `warnings`, `entrypoint`                                                          |

`StudioOverview.state` is `unconfigured`, `needs-view`, or `ready`.
`ViewInspection.freshness` is `current`, `stale`, `unbuilt`, `building`, or
`failed`.

### Provider records

| Record                 | Fields                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `ProviderReport`       | `providers`                                                                                                                  |
| `ProviderDiagnostic`   | `registration`, `distribution`, `version`, `provider_key`, `error`, `info`, `availability`, `starters` and computed `loaded` |
| `ProviderAvailability` | `available`, `version`, `reason`, `action`                                                                                   |

`ProviderDiagnostic.to_dict()` emits `key` for `provider_key`, expands
`ProviderInfo` into `schema`, `title`, `summary`, and `options`, and emits
the qualified starter IDs.

### Notebook inspection records

| Record               | Fields                                                                                                                                                                                                                        |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `InspectionResult`   | `notebook`, selected `cells`, optional `runtime`                                                                                                                                                                              |
| `NotebookSpec`       | `path`, `revision`, `cells`, `app_config`                                                                                                                                                                                     |
| `CellSpec`           | `ref`, `runtime_id`, `index`, `kind`, `name`, `source`, `code_sha256`, `preview`, `definitions`, `references`, `upstream`, `downstream`, `config`, `has_output_expression`, `may_display_output`, `markdown`, optional `code` |
| `RuntimeProbe`       | `cells`, `values`, `outputs`                                                                                                                                                                                                  |
| `RuntimeCell`        | `status`, `outputs`, `errors`                                                                                                                                                                                                 |
| `RuntimeOutput`      | `channel`, `mimetype`, `empty`                                                                                                                                                                                                |
| `ValueReadResult`    | `values`, `errors`                                                                                                                                                                                                            |
| `OutputRenderResult` | `outputs`, `errors`                                                                                                                                                                                                           |
| `ValueReadError`     | `code`, `message`                                                                                                                                                                                                             |
| `RenderedOutput`     | `owner_cell_id`, `mimetype`, `data`, `timestamp`, `reset_ui_object_ids`                                                                                                                                                       |

`InspectionResult.to_dict()` embeds runtime cell state into selected cell
records, and its top-level `runtime` field contains serialized values and value
errors. `RuntimeProbe.outputs` stays on the Python record for requested
rendered output selectors.

### Validation and browser records

| Record             | Fields                                                                                       |
| ------------------ | -------------------------------------------------------------------------------------------- |
| `ValidationReport` | `notebook`, `view`, `level`, `ok`, `issues`, `evidence`                                      |
| `ValidationIssue`  | `stage`, `severity`, `code`, `message`, `advice`, optional `view`, `target`, `source`        |
| `ShowResult`       | `notebook`, `view`, `generation`, `session_id`, `client_id`, `preview_url`, `frame_selector` |

Static and runtime evidence contain named check records. Browser checks combine
the actual document's readiness and committed revision with application
assertions. [Identities and state](identities.md#runtime-and-browser-identities)
defines presentation and runtime identities.
