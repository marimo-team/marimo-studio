---
title: Agent API reference
description: Inspect the active notebook, create and activate views, and analyze source, runtime, and rendered browser state from Marimo code mode.
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
await studio.activate_view(ctx, view.name)
report = await studio.analyze(ctx, view_name=view.name)
```

::: info Saved notebook required
The active notebook must be saved before these functions resolve its path.
:::

Keep computation, analytical context, data access, domain rules, reactive
controls, and reusable rich outputs in notebook cells. Keep page structure,
display copy, responsive layout, and presentation styling in the view files.
Use Wind4 utility classes in `index.html`. They follow the UnoCSS Wind4
vocabulary and Tailwind 4 syntax. Put custom keyframes and CSS rules in
`app.css`.

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

## `activate_view(context, name)`

```python
async def activate_view(
    context: object,
    name: str,
) -> ViewActivationResult: ...
```

Requests that connected Studio workspaces select `name`. Studio uses the same
view transition as its own selector, which preserves the workspace layout and
checks current source edits before changing views.

The returned `ViewActivationResult` contains the notebook path, view name,
`state="requested"`, and a monotonically increasing request generation. The
result confirms that the server accepted the request. Call `analyze` for the
same view to confirm that the browser loaded and read the current source
revision.

Raises:

- `ConfigurationError` when `name` is not configured for the notebook.
- `ProtocolError` when code mode has no live Studio connection, the server is
  unavailable, or the server is attached to another notebook.

## `analyze(context, *, view_name=None, timeout=10.0, require_browser=True)`

```python
async def analyze(
    context: object,
    *,
    view_name: str | None = None,
    timeout: float = 10.0,
    require_browser: bool = True,
) -> AnalysisReport: ...
```

Runs the complete agent handoff gate:

1. Static validation checks the notebook graph, view documents, projection
   references, and packaged browser assets.
2. Runtime validation executes the notebook in an isolated process and reads
   each projected cell and Python value.
3. Browser validation waits for Studio to report `ready` or `error` for the
   current saved view revision.

Static failures skip runtime validation. Browser evidence is revision-aware,
so a report recorded before the latest HTML or CSS save has state `stale`.
Pass one `view_name` after activating it for a focused repair loop. When the
name is absent, every configured view is included and each one needs current
browser evidence.

`AnalysisReport.to_dict()` returns the stable schema used by the CLI. It
contains `stages.static`, `stages.runtime`, `stages.browser`, and an `actions`
repair queue. Each action identifies its stage, severity, code, message,
advice, and available view, target, or source location.

- `report.ok` is true when no validation stage reports an error.
- `report.handoff_ready` is true when runtime validation completed, no stage
  reports an error, and every required rendered view is `ready` at the current
  revision.

Keep `require_browser=True` for agent handoff. Setting it to false limits the
gate to deterministic source and runtime evidence.

```python
while True:
    report = await studio.analyze(ctx, view_name="dashboard")
    if report.handoff_ready:
        break
    for action in report.actions:
        print(action.stage, action.advice)
    # Apply the repairs, save the affected files, and run the loop again.
```

::: warning Analysis executes notebook code
Runtime analysis can perform the notebook's configured file, network,
database, and data access. Run it in the notebook environment.
:::

Use the [coding-agent guide](../guide/coding-agents.md) for the complete
authoring workflow. Use the [CLI reference](cli.md) when the agent works
outside Marimo code mode.
