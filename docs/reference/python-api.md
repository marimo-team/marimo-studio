---
title: Python API
description: Inspect notebooks, author views, verify the current Studio tab, and serve a configured notebook.
---

# Python API

Use `marimo_studio.authoring` for a saved notebook on disk. Use
`marimo_studio.agent` inside marimo code mode when an operation needs the
current Studio tab.

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
required to reopen the workspace in another `uv` environment.

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

Summarizes one cell output by channel, MIME type, and whether its payload is
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

Describes one installed starting point, its provider, generated documents, and
current availability.

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
await view.validate(
    *,
    level: Literal["static", "runtime"] = "static",
    runtime_timeout: float = 60.0,
) -> ValidationReport
await view.export(output, *, force=False) -> StaticExportResult
await view.remove() -> ViewRemovalResult
```

`write()` checks the expected source revision under the same lock used by the
Studio editor. A stale revision raises `SourceConflictError` and preserves the
newer file.

`write()`, `build()`, `validate()`, and `export()` verify the handle's catalog
and view generation. A same-name replacement raises
`ViewGenerationConflictError` before source or artifact publication changes.
`export()` checks again before replacing its destination, including when
`force=True`.

`build()` returns the artifact revision produced by the selected development or
production build. A failed build leaves the last successful view available.

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

Contains the provider, authorized documents, source-located diagnostics, build
freshness, and retained successful build for one view.

### `StudioDiagnostic`

Names one source or build issue with a stable code, severity, repair hint, and
optional source location.

### `StaticExportResult`

Identifies the exported view, output directory, entrypoint document, and file
count returned by `View.export()`.

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

Returns installed frontend registrations, package versions, availability, and
starting points. Pass a provider key to select one registration.

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

Returns the Agent Plugin installed with the current Studio version. The plugin
contains the packaged skills and resources selected by the distribution build.
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

Returns a Marimo run-mode ASGI application that serves the notebook's default
and named views. The application lifespan opens Studio services and closes its
notebook sessions and background tasks during shutdown.

`marimo_studio.asgi:app` reads the notebook path from
`MARIMO_STUDIO_NOTEBOOK` for application servers:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app --host 127.0.0.1 --port 8000
```

### `STUDIO_RESULT_SELECTOR`

CSS selector for complete cells, rendered objects, and values that Studio has
connected to their notebook producers. Browser tools can use it to target
rendered notebook results.

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
