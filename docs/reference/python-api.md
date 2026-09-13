---
title: Python API
description: Inspect notebooks, author views, verify the current Studio tab, and serve a configured notebook.
---

# Python API

Use `marimo_studio.authoring` for a saved notebook on disk. Use
`marimo_studio.agent` inside
[Marimo code mode](https://docs.marimo.io/guides/editor_features/tools/#code-mode)
when an operation needs the current Studio tab. Code mode gives a coding agent
a Python execution inside the live notebook kernel. Public records are frozen
dataclasses. Their `to_dict()` methods produce the schema used by
`marimo-studio --json`.

## `marimo_studio.authoring`

### `open_workspace`

```python
from marimo_studio.authoring import open_workspace

workspace = open_workspace("analysis.py")
```

```text
open_workspace(notebook: str | Path) -> Workspace
```

Returns a workspace handle for an existing regular file. The call resolves the
path and verifies the file. It raises `ConfigurationError` when the resolved path
is not a regular file. Each operation loads and validates the notebook and Studio
configuration it needs.

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

Static notebook inspection never executes notebook code. Runtime inspection
and runtime validation execute the complete notebook in an owned child process.
The child inherits the interpreter environment, current directory, OS user
permissions, filesystem access, and network access. The process boundary owns
cleanup and terminates the child process tree after cancellation or a timeout.
It is a lifecycle boundary, not a security sandbox. Run trusted notebook code.

Use `context="upstream"` with one or more selectors to include every cell that
produces their inputs.

`create_view()` raises `ViewExistsError` when the name already has a view.
`view()` reads the current catalog and returns a handle bound to that workspace
and view incarnation. `create_view()` and `bind()` reject a replacement
workspace with `WorkspaceGenerationConflictError`. Open a new workspace before
retrying the operation.

### `StudioOverview`

Describes the configuration source, notebook, view root, runtime choices, cell
aliases, and configured views returned by `Workspace.status()`.
`generation` identifies the returned catalog and changes when its configuration
or view incarnations change.

`launch_requirements` lists the exact Studio requirement with configured
provider extras and the exact installed third-party provider distributions
required to reopen the workspace in another `uv` environment. The `uv`
executable must be available when Studio needs to prepare or re-enter that
environment.

### `ViewOverview`

Identifies one configured view, its project path, provider, Source document
paths, default status, generation, and current artifact revision. Call
`View.inspect()` to read each document's access mode.

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
Run `marimo-studio view create VIEW --target PATH --dry-run` to inspect the
complete created file set before committing it. `Workspace.create_view()`
creates the view directly.

### `BindingResult`

Identifies the alias, selected notebook cell, configuration path, and previous
binding returned by `Workspace.bind()`. `catalog_generation` identifies the
post-commit catalog captured by the owning workspace.

### `View`

`View` binds view operations to one workspace and name.
`catalog_generation` and `generation` identify the catalog and view incarnation
that the handle observed.

Successful `Workspace.bind()`, `Workspace.create_view()`, and `View.remove()`
advance the owning `Workspace`. Existing `View` handles remain bound to their
original generations. Reacquire them with `workspace.view(name)` after a catalog
mutation.

Use Studio's remove and create operations for same-name replacement. Direct
filesystem delete and recreation completed between observations is outside the
0.1 mutation-ownership contract when it reuses `(device, inode, mode)`. This
includes exact-byte recreation.

```text
await view.inspect() -> ViewInspection
await view.read(path) -> ViewDocument
await view.write(path, content, *, expected_revision) -> ViewDocument
await view.build(*, profile="development") -> ViewBuild
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
await view.remove() -> ViewRemovalResult
```

`inspect()` reads current filesystem state. Source can be edited through
filesystem tools or `write()`. Provider inspection continues to own document
access and build-input discovery. See [Manage view source](../guide/manage-source.md)
for multi-file edits and recovery.

`write()` checks the expected source revision under the same lock used by the
Studio editor. A stale revision raises `SourceConflictError` and preserves the
newer file.

`show()`, `write()`, `build()`, `validate()`, `preflight()`, and `export()`
verify the handle's catalog and view generation. A same-name replacement raises
`ViewGenerationConflictError` before browser activation, source writes, or
artifact publication. `export()` checks again before replacing its destination,
including when `force=True`.

`preflight()` builds, prepares, and inspects the complete static bundle in a
temporary directory. It returns before publishing a caller-owned destination.
`export()` runs the same preflight before it writes one static runtime.
`runtime="zero-python"` prepares the configured notebook states.
`runtime="wasm"` packages notebook source for execution through Pyodide in each
visitor's browser.
`prepare_timeout` bounds Zero-Python preparation and uses 30 seconds when
omitted. Passing `prepare_timeout` with `runtime="wasm"` raises `ValueError`
before Studio loads the workspace or builds the provider artifact.

`progress` receives ordered `StaticExportProgress` records from the synchronous
export worker. Each record wraps either a `marimo_export.ProgressEvent` or a
Studio-owned `StaticExportStep`. Keep callbacks fast and thread-safe. An
exception raised by the callback cancels static destination publication.

`build()` returns the artifact revision produced by the selected development or
production build. The profiles maintain independent publications. A failed
build leaves the last successful artifact for that profile available.

### `View.hold_publication` and `View.release_publication`

```text
await view.hold_publication(*, owner: str, ttl: float = 300.0) -> PublicationHold
await view.release_publication(token: str) -> PublicationHold | None
```

`hold_publication()` delays replacement publication across processes while
source editing remains available. Existing published artifacts can be reused.
`owner` identifies the editor and must contain 1 to 256 characters, including
at least one non-whitespace character. `ttl` is a finite number of seconds
greater than zero and at most 3600. Invalid arguments raise `ValueError`.
An active hold raises `ConfigurationError` with its owner and expiry.

Retain the returned token. `release_publication()` releases the matching hold
and returns its receipt. Repeating the release returns the same receipt.
It returns `None` when the view has no hold record. A mismatched token raises
`ConfigurationError`. Both methods enforce the handle's view generation.
They remain available when the manifest needs repair.

Release or expiry permits the live editor to reconcile and publish current
source. For an offline workflow, call `build()` after release. Source changes
remain on disk after release, expiry, or editing-process exit.

### `PublicationHold`

Contains `token`, `owner`, view `generation`, `expires_at` as Unix seconds, and
`released`. The computed `status` is `active`, `expired`, or `released`.
`to_dict()` includes `status` with the token, owner, generation, and expiry.

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

Provider or manifest failure returns diagnostics and an incomplete inventory.
Repair `view.toml` through its manifest path, then inspect again. Artifact
metadata describes disk publication. Browser validation provides evidence for
one rendered Studio presentation. See [Identities and
state](identities.md#build-freshness) for freshness values.

```text
inspection.changes_since(previous: ViewInspection) -> ViewSourceChanges
```

Compares file revisions from two complete inventories. Raises `ValueError`
when either inventory is incomplete or the root, view, or generation differs.

When `view.toml` needs repair, `provider` is `None`, the inventory is incomplete,
and publication fields describe stored build receipts. Repair the manifest and
inspect again to verify the provider and artifact.

### `ViewSourceFile`

`ViewSourceFile` contains a project-relative `path` and content `revision`.
A `None` revision records an expected file that is missing.

### `ViewSourceChanges`

`ViewSourceChanges` contains `added`, `modified`, and `deleted` path tuples.
Its `to_dict()` serializes each tuple as a list of forward-slash paths.

### `StudioDiagnostic`

Names one source or build issue with a stable code, severity, repair hint, and
optional source location.

### `StaticRuntime`

`Literal["zero-python", "wasm"]`. The value selects the single notebook runtime
written into a static export.

### `StaticExportResult`

Contains `notebook`, `view`, selected `runtime`, provider artifact `document`,
`cache_activity`, `preflight`, and marimo-export's `DeliveryResult`. The
`output`, `files`, and `warnings` properties expose the committed delivery.
A Zero-Python result carries marimo-export's authored and projection cache
dispositions. A WebAssembly result sets `cache_activity` to `None`. The
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
`marimo_export` when code needs to distinguish preparation events from Studio
steps. `StaticExportEvent` is the union of those two records.

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
| `verification-required` | Zero-Python still needs to capture the target's configured states.    |
| `verified`              | Zero-Python captured the target through the completed preflight.      |
| `incompatible`          | The selected runtime cannot represent the authored projection target. |

### `StaticPreflightIssue`

Names one source-located delivery diagnostic with `code`, `severity`,
`message`, optional `reference`, and `hint`. Errors stop export before the
destination changes. Warnings identify browser dependencies that require
caller review.

### `ViewRemovalResult`

Identifies the removed view, the updated default view, and the remaining view
names returned by `View.remove()`. `catalog_generation` identifies the
post-commit catalog captured by the owning workspace.

`remove()` raises `ViewInUseError` while another process holds an artifact
lease for the view. A catalog change, including a same-name replacement, raises
`WorkspaceGenerationConflictError` and requires a new `Workspace` and `View`
handle. `ViewDeletionError` reports an incomplete filesystem cleanup and
exposes the cleanup path through `diagnostic_details()`.

### `ValidationReport`

```text
ValidationReport(
    notebook: Path,
    view: str | None,
    level: Literal["static", "runtime", "browser"],
    ok: bool,
    issues: tuple[ValidationIssue, ...],
    evidence: Mapping[str, object],
)
```

`ok` answers whether the requested validation completed against one coherent
source and runtime state. Browser validation also requires current evidence from
the selected rendered view.

### `ValidationIssue`

```text
ValidationIssue(
    stage: Literal["validation", "static", "runtime", "browser"],
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
false. Warnings remain available for task-specific judgment.

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

### `agent_plugin`

```python
import marimo_studio.agent as studio_agent

resources = studio_agent.agent_plugin()
```

```text
agent_plugin() -> agent_plugins.Plugin
```

Returns the [Agent Plugin](https://github.com/peter-gy/agent-plugins) installed
with the current Studio version. An Agent Plugin packages skills and related
resources for coding agents. Studio's plugin contains the skills and resources
selected by the distribution build.
Raises `AgentPluginError` when the installed distribution has no usable plugin.

### `agent_skill`

```python
skill = studio_agent.agent_skill()
print(skill.body)
```

```text
agent_skill() -> agent_plugins.Skill
```

Returns Studio's packaged `marimo-studio` skill. The dynamic module help points
to the same skill and its installed `SKILL.md`. Raises `AgentPluginError` when
the packaged plugin does not contain that skill.

### `current_workspace`

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
```

```text
current_workspace() -> Workspace
```

Returns the live `Workspace` for the current code-mode notebook and Studio tab.
Call it once in each code-mode execution.

### `Workspace`

The live workspace supports the saved-notebook operations documented in
`marimo_studio.authoring`. Workspace-wide validation remains static or runtime
validation.

### `View`

The live view adds the browser operations:

```text
await view.show() -> ShowResult
await view.validate(
    *,
    level: Literal["static", "runtime", "browser"] = "static",
    browser_timeout: float = 10.0,
    runtime_timeout: float = 60.0,
) -> ValidationReport
```

`show()` selects the view in the current Studio tab. Run it in a separate
code-mode execution before browser validation so the view can finish rendering.

Browser validation requires one view. Exercise relevant view interactions
before requesting the report.

### `ShowResult`

```text
ShowResult(
    notebook: Path,
    view: str,
    generation: int,
    session_id: str,
    client_id: str,
)
```

Confirms that the intended Studio tab accepted the view selection.
`generation` is the tab's monotonically increasing activation generation. It
is distinct from the 64-character view generation used for mutation ownership.

### `PublicationHold`

The live API returns the same [publication hold](#publicationhold) record as
saved-workspace authoring.

### `ViewInspection`

The live API returns the same [source inspection](#viewinspection) record as
saved-workspace authoring. Its source evidence describes saved files.

### `ViewSourceFile`

The live API uses the common [file revision](#viewsourcefile) record.

### `ViewSourceChanges`

The live API uses the common [source comparison](#viewsourcechanges) record.

### `ValidationReport`

The live API returns the common validation record documented under
`marimo_studio.authoring`.

### `ValidationIssue`

The live API returns the common issue record documented under
`marimo_studio.authoring`.

## `marimo_studio`

### `inspect_notebook`

```python
from marimo_studio import inspect_notebook

notebook = inspect_notebook("analysis.py", include_code=True)
```

```text
inspect_notebook(path: str | Path, *, include_code: bool = False) -> NotebookSpec
```

Compiles the saved notebook and returns its cells, source spans, definitions,
references, and dependency relationships without executing it.

### `create_asgi_app`

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("analysis.py")
```

```text
create_asgi_app(notebook: str | Path) -> ASGIApp
```

Returns a Marimo run-mode [ASGI](https://asgi.readthedocs.io/en/latest/)
application that serves the notebook's default and named views. ASGI is the
standard interface between asynchronous Python web applications and servers.
The application lifespan opens Studio services and closes its notebook
sessions and background tasks during shutdown.

Forward the application lifespan through the ASGI server. Marimo owns
authentication and supplies read and edit scopes to Studio routes. The hosting
stack owns TLS, proxy headers, process supervision, network exposure, and
resource limits. See [Compatibility and
support](compatibility.md#deployment-boundary).

`marimo_studio.asgi:app` reads the notebook path from
`MARIMO_STUDIO_NOTEBOOK` for application servers:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app --host 127.0.0.1 --port 8000
```

### `STUDIO_RESULT_SELECTOR`

CSS selector for connected cell, output, and value hosts, parents containing
hidden value hosts, and custom regions annotated with `data-marimo-lens-inputs`.
See [custom JavaScript rendering](projections.md#trace-custom-javascript-rendering)
for the authoring contract.

Pass the selector to [Marimo Lens](https://marimo-team.github.io/marimo-lens/)
to collect feedback from native projections and custom rendered regions:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
```

Render `studio_lens` through `<marimo-output value="studio_lens">` in the view.
Lens reads resolved producer and value-selector metadata from the linked hosts.
For page regions without notebook inputs, extend `dom_selector` with another
focused CSS selector.

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

The complete class, code, status, and recovery table is in [Errors and
JSON](errors-and-json.md#public-error-classes).

## Public records

These tables list fields that have related names across command and Python
surfaces. Nested notebook records are documented under `NotebookSpec` and
`InspectionResult`.

### Workspace and view records

| Record               | Fields                                                                                                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `StudioOverview`     | `notebook`, `state`, `generation`, `config_path`, `config_source`, `view_root`, `default_view`, `default_runtime`, `runtimes`, `bindings`, `views`, `launch_requirements` |
| `ViewOverview`       | `name`, `generation`, `path`, `default`, `provider`, `documents`, `artifact_revision`                                                                                     |
| `Starter`            | `id`, `title`, `summary`, `provider`, `documents`, `availability`                                                                                                         |
| `BindingResult`      | `alias`, `cell`, `config_path`, `catalog_generation`, `dry_run`, `previous_ref`                                                                                           |
| `ViewDocument`       | `path`, `language`, `access`, `content`, `revision`                                                                                                                       |
| `ViewInspection`     | `view`, `provider`, `documents`, `diagnostics`, `freshness`, `build`                                                                                                      |
| `ViewBuild`          | `view`, `profile`, `revision`, `issues`                                                                                                                                   |
| `ViewRemovalResult`  | `notebook`, `view`, `default_view`, `views`, `catalog_generation`                                                                                                         |
| `StaticExportResult` | `notebook`, `view`, `runtime`, `document`, `cache_activity`, `preflight`, `delivery` and computed `output`, `files`, `warnings`, `entrypoint`                             |

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
`ProviderInfo` into `schema`, `title`, `summary`, and `api_version`, and emits
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
records. Its top-level `runtime` field contains serialized values and value
errors. `RuntimeProbe.outputs` remains available on the Python record for
requested rendered output selectors.

### Validation and browser records

| Record             | Fields                                                                                |
| ------------------ | ------------------------------------------------------------------------------------- |
| `ValidationReport` | `notebook`, `view`, `level`, `ok`, `issues`, `evidence`                               |
| `ValidationIssue`  | `stage`, `severity`, `code`, `message`, `advice`, optional `view`, `target`, `source` |
| `ShowResult`       | `notebook`, `view`, `generation`, `session_id`, `client_id`                           |

Static and runtime evidence contain named check records. Browser evidence adds
presentation revisions, runtime identity, browser observations, runtime status,
and projection instance state. [Identities and
state](identities.md#runtime-and-browser-identities) defines the identity
relationships.
