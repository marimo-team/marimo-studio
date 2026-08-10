---
title: Agent API reference
description: Inspect the active notebook, create views, bind cell aliases, and validate projections from Marimo code mode.
---

# Agent API reference

`marimo_studio.agents` adapts the saved notebook and Studio workspace for a
coding agent running in Marimo code mode.

```python
import marimo._code_mode as cm
import marimo_studio.agents as studio

ctx = cm.get_context()
notebook = studio.inspect(ctx, include_code=True)
view = studio.ensure_view(ctx, "dashboard")
```

::: info Saved notebook required
The active notebook must be saved before these functions resolve its path.
:::

## `notebook_path(context)`

```python
notebook_path(context: object) -> pathlib.Path
```

Returns the saved notebook path from a code-mode context.

Raises:

- `TypeError` when `context` has no globals mapping.
- `RuntimeError` when the active notebook has not been saved.
- `FileNotFoundError` when the saved path is unavailable.

## `inspect(context, *, include_code=False)`

```python
inspect(
    context: object,
    *,
    include_code: bool = False,
) -> NotebookSpec
```

Compiles the saved notebook and returns its cells, source positions, names,
definitions, references, configuration, and dependency relationships. It
leaves notebook cells unevaluated.

Set `include_code=True` to include each complete cell body in `CellSpec.code`.

## `ensure_view(context, name=None, *, dry_run=False)`

```python
ensure_view(
    context: object,
    name: str | None = None,
    *,
    dry_run: bool = False,
) -> ViewSetupResult
```

Returns the current files for a named view. The function creates the view and
updates notebook configuration when the view is missing. A new view starts
with every notebook cell in source order.

The default name is the configured view or `dashboard`. Set `dry_run=True` to
return the planned paths and configuration changes without writing files.

`ViewSetupResult.root` is the view directory. Its initial authored files are
`index.html` and `app.css`.

## `bind(context, alias, cell_index, *, dry_run=False, overwrite=False)`

```python
bind(
    context: object,
    alias: str,
    cell_index: int,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult
```

Records `alias` as a stable reference to the cell at zero-based
`cell_index`. Set `overwrite=True` when the alias should point to a different
cell. Set `dry_run=True` to return the planned configuration update.

Use a native Marimo cell name directly when one exists.

## `check(context, *, view_name=None)`

```python
check(
    context: object,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]
```

Compiles the saved notebook and checks the configured view documents, cell
references, rich-output references, and JSON-compatible value references. It
leaves notebook cells unevaluated.

Pass `view_name` to check one named view. The default checks every configured
view. Each `CheckResult.status` is `pass`, `warn`, or `fail`.

```python
results = studio.check(ctx, view_name="dashboard")
failures = [result for result in results if result.status == "fail"]
```

Use the [coding-agent guide](../guide/coding-agents.md) for the complete
authoring workflow. Use the [CLI reference](cli.md) when the agent works
outside Marimo code mode.
