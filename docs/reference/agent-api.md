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
activation = await studio.activate_view(ctx, view.name)
```

Let that code-mode call return so a first view can reload the native editor
into Studio. Run the analysis in the next code-mode call after the page loads:

```python
import marimo._code_mode as cm
import marimo_studio.agents as studio

ctx = cm.get_context()
report = await studio.analyze(ctx, view_name="dashboard")
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

Selects `name` in the current browser workspace. An active Studio workspace
uses the same in-place transition as its selector, which preserves the layout
and checks current source edits. The request targets the Studio tab attached
to the current Marimo session. When the notebook gained its first Studio view
during that native editor session, Marimo reloads the page into the selected
Studio view after the code-mode call returns.

The returned `ViewActivationResult` contains the notebook path, view name,
a monotonically increasing generation, and the selected transition.
`state="active"` with `transition="in-place"` means the targeted workspace
acknowledged the completed transition. `state="reload-requested"` with
`transition="reload"` means the exact native editor session will reload after
the code-mode call releases its execution lock. Call `analyze` for the same
view to confirm that the rendered page read the current source revision.

Raises:

- `ConfigurationError` when `name` is not configured for the notebook.
- `ProtocolError` when code mode has no live Marimo callback credentials.
- `AgentRequestError` when the server, session, or targeted browser cannot
  complete the transition, or when the server is attached to another
  notebook. The exception's `code` identifies the failure.

## `analyze(context, *, view_name=None, timeout=10.0, runtime_timeout=60.0, require_browser=True)`

```python
async def analyze(
    context: object,
    *,
    view_name: str | None = None,
    timeout: float = 10.0,
    runtime_timeout: float = 60.0,
    require_browser: bool = True,
) -> AnalysisReport: ...
```

Runs the complete agent handoff gate:

1. Static validation checks the notebook graph, view documents, projection
   references, and packaged browser assets.
2. Runtime validation executes the notebook in an isolated process and reads
   each projected cell and Python value.
3. Browser validation issues a fresh request to the session-bound Studio tab
   and waits for `ready` or `error` for the selected runtime instance and
   saved source revision.

Code mode delegates this work to the attached Studio server. The server runs
the isolated validation process and returns one structured report to the
active notebook kernel.

Static failures skip runtime validation. Runtime and browser checks use one
captured revision map. An edit during analysis adds an
`analysis-source-changed` action, so evidence from different saves cannot
produce a handoff-ready report. Code mode requires one named, active view for
browser validation. Activate the view in one code-mode call, let that call
finish, then analyze it in the next call. Setting `require_browser=False`
allows a code-mode call with no `view_name` to validate every configured view
through the static and isolated runtime stages. The external
`marimo-studio analyze` command can visit every configured view because it does
not occupy the notebook kernel while Studio switches views.

`AnalysisReport.to_dict()` returns the stable schema used by the CLI. It
contains `stages.static`, `stages.runtime`, `stages.browser`, and an `actions`
repair queue. Each action identifies its stage, severity, code, message,
advice, and available view, target, or source location.

- `report.ok` is true when no validation stage reports an error.
- `report.handoff_ready` is true when runtime validation completed, no stage
  reports an error, and every required rendered view is `ready` for the report
  runtime, revision, runtime instance, Marimo session, browser client, and
  request ID.

Keep `require_browser=True` for agent handoff. Setting it to false limits the
gate to deterministic source and runtime evidence.

`timeout` must be finite and between 0 and 20 seconds. It bounds the rendered
browser observation. `runtime_timeout` must be finite and between 0 and 300
seconds. It bounds isolated notebook execution and defaults to 60 seconds. A
runtime deadline produces a `runtime-timeout` action with repair advice.
Transport, protocol, authentication, session, revision, and rendered-view
failures appear as stable error codes in `actions` or raise
`AgentRequestError` before a report can be created.

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
