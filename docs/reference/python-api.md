---
title: Python API
description: Inspect notebooks, author pages, verify the current Studio tab, and serve a configured notebook.
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

Opens one saved notebook for inspection, page authoring, builds, static or
runtime validation, export, and removal. Raises `ConfigurationError` when the
path does not identify a saved notebook.

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
and runtime validation execute the complete notebook in an isolated process.
Use `context="upstream"` with one or more selectors to include every cell that
produces their inputs.

`create_view()` raises `ViewExistsError` when the name already has a page.
`view()` returns a handle without reading the filesystem. Operations on that
handle report a missing or invalid page.

### `View`

`View` binds page operations to one workspace and name.

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

`build()` returns the page revision produced by the selected development or
production build. A failed build leaves the last successful page available.

### `ViewBuild`

```text
ViewBuild(
    view: str,
    profile: Literal["development", "production"],
    revision: str,
    issues: tuple[ProjectDiagnostic, ...],
)
```

Describes one successful page build. `revision` identifies the complete browser
output.

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
the selected rendered page.

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

## `marimo_studio.agent`

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
code-mode execution before browser validation so the page can finish rendering.

Browser validation requires one view. Exercise relevant page interactions
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

Confirms that the intended Studio tab accepted the page selection.

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
and named pages. The application lifespan opens Studio services and closes its
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
