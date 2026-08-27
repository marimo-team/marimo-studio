---
title: Agent API reference
description: Open one notebook workspace, author its views, and validate the rendered result from Marimo code mode.
---

# Agent API reference

`marimo_studio.agent` binds Studio operations to the active saved notebook.

```python
import marimo_studio.agent as studio

workspace = studio.open()
view = await workspace.ensure_view("dashboard")
inspection = await view.inspect()
```

Call `studio.open()` once in each code-mode execution. Use
`workspace.view(name)` to recover a view handle in a later execution. Build,
activation, and browser validation each run in their own execution so the
browser can settle between transitions.

## `open()`

```python
open(notebook: str | Path | None = None) -> Workspace
```

Returns a workspace bound to the saved notebook attached to the current Marimo
code-mode request. Pass `notebook` for a path-bound workspace outside code mode.

Raises:

- `ProtocolError` when the call is outside code mode or the attached notebook
  path is unavailable.
- `ConfigurationError` when an explicit notebook path is not a file.

## `Workspace`

### `Workspace.inspect`

```python
await workspace.inspect(
    *,
    include_code: bool = False,
    selectors: tuple[CellSelector, ...] = (),
    output_expressions: bool = False,
    limit: int | None = None,
) -> InspectionResult
```

Compiles the saved notebook and returns selected cells and their static
dependency relationships. The call leaves cell bodies unevaluated.
`selectors` accepts exact cell refs, names, or zero-based indices. Inspect the
inventory first, then request code for the producer and its `upstream` refs.
`output_expressions=True` filters the saved cells to bodies whose final
statement is an expression. It does not inspect current runtime output.

### `Workspace.overview`

```python
await workspace.overview() -> StudioOverview
```

Returns notebook configuration and view state. The result works before Studio
configuration exists.

### `Workspace.starters`

```python
await workspace.starters() -> tuple[Starter, ...]
await workspace.starter(identity: str) -> Starter
```

Returns installed view starters and their availability. `Starter.id` has
`provider:key` form, such as `marimo-studio/vanilla:default`. Pass the returned
record to `Workspace.ensure_view` when selecting a starter.

### `Workspace.ensure_view`

```python
await workspace.ensure_view(
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
) -> View
```

Creates the named view when needed and returns its handle. The default name is
the configured view or `dashboard`. An omitted starter selects
`marimo-studio/vanilla:default`. A newly created view is `unbuilt` until
`View.build()` or a live preview publishes it.

For notebook-local configuration, creation writes the PEP 723 metadata and
provider requirements, updates the existing workspace `.gitignore`, writes
`view.toml`, then writes provider starter files. These writes commit through
one filesystem transaction.

### `Workspace.view`

```python
workspace.view(name: str) -> View
```

Returns a handle for a named view. The method performs no I/O. Operations on
the handle report a missing or invalid project.

### `Workspace.bind`

```python
await workspace.bind(
    alias: str,
    cell_index: int,
    *,
    overwrite: bool = False,
) -> BindingResult
```

Assigns `alias` to the notebook cell at zero-based `cell_index`. Use native
Marimo cell names for new view-facing results.

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

`level` accepts `static`, `runtime`, or `browser`. Each level includes the
evidence from the previous level. Browser validation requires one focused view
and an attached Studio browser. Runtime validation starts the complete reactive
notebook in an isolated process and can perform its configured file, network,
database, and data access. Studio then checks the selected projected results.

## `View`

### `View.inspect`

```python
await view.inspect() -> ViewInspection
```

Returns the provider, source documents and access, diagnostics, build
freshness, and the current publication. The document catalog contains the core
`view.toml` manifest followed by the provider's authoring documents.
`freshness` is `current`, `stale`, `unbuilt`, `building`, or `failed`.

### `View.read` and `View.write`

```python
document = await view.read(path: str | PurePosixPath) -> ViewDocument
updated = await view.write(
    path: str | PurePosixPath,
    content: str,
    *,
    expected_revision: str,
    expected_provider: str | None = None,
) -> ViewDocument
```

`ViewDocument` contains `path`, `language`, `access`, `content`, and `revision`.
`write()` checks access and compares `expected_revision` under the same source
lock used by Studio browsers. A stale revision raises `SourceConflictError`.
Its `revision` is the current disk revision when readable and `None` when the
document is unavailable. When `external_recovery` is set, inspect and preserve
the file at that path before retrying the write.

`expected_provider` applies to `view.toml`. When supplied, the replacement must
declare that provider. A parseable current manifest always retains its provider.
If a cold process cannot recover the prior identity from a malformed manifest,
omit `expected_provider`. Studio then validates the provider declared by the
replacement. Invalid manifest content and provider changes raise
`SourceValidationError`. Passing `expected_provider` for another document raises
`ValueError`.

### `View.build`

```python
await view.build(*, profile: BuildProfile = "development") -> Publication
```

Builds `development` or `production` output and returns detached publication
metadata. `Publication` contains `view`, `profile`, `input_id`, `artifact_id`,
`diagnostics`, and `duration_ms`. A failed build preserves the last published
page.

### `View.activate`

```python
await view.activate() -> ViewActivationResult
```

Selects the view in the Studio browser attached to the current Marimo session.
The result identifies the browser client and session that acknowledged the
selection.

### `View.validate`

```python
await view.validate(
    *,
    level: ValidationLevel = "static",
    browser_timeout: float = 10.0,
    runtime_timeout: float = 60.0,
) -> ValidationReport
```

Validates this view at the selected level. `ValidationReport` keeps stable
`ok`, `actions`, and `evidence` fields. Static evidence contains saved-source
checks. Runtime and browser levels add their evidence under the same mapping.
Exercise relevant interactions before browser validation so the report
describes the state being handed off.

## Returned records

Import `CellSelector`, `InspectionResult`, and direct authoring records from
`marimo_studio.agent`. Static notebook records returned by `inspect_notebook()`
live in `marimo_studio`. Provider records live in
`marimo_studio.view_providers`.

[Agent workflow](../guide/coding-agents.md) develops the authoring and repair
sequence. [CLI reference](cli.md) defines the terminal interface.
