---
title: Agent API reference
description: Inspect a saved notebook and author, validate, activate, export, or remove its Studio views from Marimo code mode.
---

# Agent API reference

`marimo_studio.agent` binds the shared Studio authoring services to the active
saved notebook and browser.

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = await workspace.create_view("dashboard")
inspection = await view.inspect()
```

Call `studio.open()` once in each code-mode execution. Use
`workspace.view(name)` to recover a view handle in a later execution. Build,
activation, and browser validation run in separate executions so the browser
can settle between transitions.

## `open()`

```python
open(notebook: str | Path | None = None) -> Workspace
```

Returns a workspace bound to the saved notebook attached to the current Marimo
code-mode request. Pass `notebook` for a path-bound workspace outside code mode.

Raises `ProtocolError` when the active code-mode notebook is unavailable and
`ConfigurationError` when the selected notebook is missing.

## `doctor()`

```python
await doctor(provider: str | None = None) -> ProviderReport
```

Returns finalized provider registration, package, availability, and starter
diagnostics. Pass a provider key to select one registration.

## `Workspace`

### `Workspace.status`

```python
await workspace.status() -> StudioOverview
```

Returns notebook configuration and view state. The result also works before the
notebook has a Studio configuration.

### `Workspace.inspect_notebook`

```python
await workspace.inspect_notebook(
    *,
    runtime: bool = False,
    include_code: bool = False,
    selectors: tuple[CellSelector, ...] = (),
    output_expressions: bool = False,
    limit: int | None = None,
    runtime_timeout: float = 60.0,
) -> InspectionResult
```

Returns selected saved cells and their static dependency relationships.
`selectors` accepts exact cell refs, names, or zero-based indices. Set
`include_code=True` after selecting the producer and its upstream cells.

Set `runtime=True` to execute the complete notebook in an isolated process.
Runtime inspection adds bounded MIME outputs and JSON values for the selected
cells. The notebook can perform its configured file, network, database, and
data access during execution.

### `Workspace.starters`

```python
await workspace.starters() -> tuple[Starter, ...]
```

Returns installed view starters and their availability. `Starter.id` has
`provider:key` form, such as `marimo-studio/vanilla:default`.

### `Workspace.create_view`

```python
await workspace.create_view(
    name: str,
    *,
    starter: str | Starter | None = None,
) -> View
```

Creates one named view and returns its handle. An omitted starter selects
`marimo-studio/vanilla:default`. The call raises `ViewExistsError` when `name`
already exists. Use `workspace.view(name)` for an existing view.

Creation validates the notebook and starter, updates notebook-local metadata
and provider requirements when required, then writes `view.toml` and provider
source through one filesystem transaction.

### `Workspace.view`

```python
workspace.view(name: str) -> View
```

Returns a handle for one named view. The method performs no I/O. Operations on
the handle report a missing or invalid project.

### `Workspace.bind`

```python
await workspace.bind(
    alias: str,
    cell: CellSelector,
    *,
    overwrite: bool = False,
) -> BindingResult
```

Assigns `alias` to a notebook cell selected by ref, name, or zero-based index.
Use native Marimo cell names for new view-facing results.

### `Workspace.validate`

```python
await workspace.validate(
    *,
    level: ValidationLevel = "static",
    view: str | None = None,
    browser_timeout: float = 10.0,
    runtime_timeout: float = 60.0,
) -> ValidationReport
```

`level` accepts `static`, `runtime`, or `browser`. Each level includes evidence
from the previous level. Omit `view` to validate every configured view. Browser
validation uses the Studio browser attached to the current code-mode request.

## `View`

### `View.inspect`

```python
await view.inspect() -> ViewInspection
```

Returns the provider, source document catalog, diagnostics, build freshness,
and current publication. `freshness` is `current`, `stale`, `unbuilt`,
`building`, or `failed`.

### `View.read`

```python
await view.read(path: str | PurePosixPath) -> ViewDocument
```

Returns one authorized text document. `ViewDocument` contains `path`,
`language`, `access`, `content`, and `revision`.

### `View.write`

```python
await view.write(
    path: str | PurePosixPath,
    content: str,
    *,
    expected_revision: str,
) -> ViewDocument
```

Checks document access and compares `expected_revision` under the same source
lock used by Studio browsers. A stale revision raises `SourceConflictError` and
preserves the newer file. A successful write preserves the file mode and
replaces the source atomically.

### `View.build`

```python
await view.build(
    *,
    profile: BuildProfile = "development",
) -> Publication
```

Builds `development` or `production` output. `Publication` contains `view`,
`profile`, `input_id`, `artifact_id`, `diagnostics`, and `duration_ms`. A failed
candidate preserves the current publication.

### `View.activate`

```python
await view.activate() -> ViewActivationResult
```

Selects the view in the Studio browser attached to the current code-mode
request. The result identifies the browser client and session that acknowledged
the selection.

### `View.validate`

```python
await view.validate(
    *,
    level: ValidationLevel = "static",
    browser_timeout: float = 10.0,
    runtime_timeout: float = 60.0,
) -> ValidationReport
```

Validates this view at the selected level. `ValidationReport` contains `ok`,
`actions`, `evidence`, and `handoff_ready`. Exercise relevant interactions
before browser validation so the report describes the presentation being
handed off.

### `View.export`

```python
await view.export(
    output: str | Path,
    *,
    force: bool = False,
) -> StaticExportResult
```

Builds the production artifact and writes a static WebAssembly site. `force`
allows replacement of an existing destination after Studio validates the
output boundary.

### `View.remove`

```python
await view.remove() -> ViewRemovalResult
```

Removes the complete view project and returns the remaining view inventory.
Studio retains at least one configured view and updates the default when the
selected view owned it.

[Author views with a coding agent](../guide/coding-agents.md) develops the
authoring workflow. [CLI reference](cli.md) defines the terminal interface.
