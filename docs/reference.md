# CLI and configuration

`marimo-studio` configures views, inspects notebook cells, records aliases, and
validates projections. This reference also defines notebook configuration,
view elements, browser state, and routes. See
[Create your first view](getting-started.md) for a complete first run.

## Command line

```text
marimo-studio [NOTEBOOK] [OPTIONS] [-- MARIMO_ARGS]
marimo-studio inspect [OPTIONS] [NOTEBOOK]
marimo-studio bind [OPTIONS] ALIAS [NOTEBOOK]
marimo-studio view add [OPTIONS] NAME [NOTEBOOK]
marimo-studio view list [OPTIONS] [NOTEBOOK]
marimo-studio check [OPTIONS] [NOTEBOOK]
```

Pass a notebook path when creating the first view. After setup, commands can
discover the configured notebook from its directory or project.

### Open Studio

```console
uvx marimo-studio analysis.py --view executive
```

The direct command configures the notebook when needed, creates a blank view,
starts the native Marimo editor, and prints the Studio workspace and standalone
view URLs. It opens the workspace with the selected view.

| Option | Default | Behavior |
| --- | --- | --- |
| `--view NAME` | Configured default | Opens the named view |
| `--host HOST` | `127.0.0.1` | Binds the Marimo server to this host |
| `--port PORT` | `8000` | Binds to a port from `1` through `65535` |
| `--base-url PATH` | Empty | Serves beneath a path such as `/proxy/app` |
| `--open / --headless` | `--open` | Controls browser launch |
| `-- MARIMO_ARGS` | Empty | Forwards trailing arguments to `marimo edit` |

Put host, port, base URL, and browser options before `--`. Studio prepares the
notebook environment, so omit Marimo sandbox flags. Run the native command when
the server needs `--proxy`:

```console
uv run --with marimo-studio marimo edit analysis.py --proxy PROXY_URL
```

### Inspect notebook cells

```console
uvx marimo-studio inspect analysis.py --display
```

Use `inspect` to compile the notebook graph and print one record per cell.

| Option | Behavior |
| --- | --- |
| `--display` | Keeps cells with a final displayed expression |
| `--include-code` | Adds each complete cell body |
| `--runtime` | Executes the notebook and adds MIME output and JSON-compatible values |
| `--limit N` | Returns at most `N` cell records |
| `--format text\|json` | Selects human or machine output |

Static inspection leaves cell bodies unevaluated. Runtime inspection executes
the notebook in its configured environment and can perform its file, network,
database, and data access.

### Bind an anonymous cell

```console
uvx marimo-studio bind summary analysis.py --cell 12
```

Use `bind` to record a stable alias for the zero-based cell index.

| Option | Behavior |
| --- | --- |
| `--cell INDEX` | Selects the zero-based notebook cell |
| `--dry-run` | Reports the binding and leaves configuration unchanged |
| `--overwrite` | Replaces an existing alias |
| `--format text\|json` | Selects human or machine output |

Native Marimo cell names need no binding. Alias names start with a letter and
contain letters, digits, underscores, or hyphens.

Your alias follows the bound cell across ordinary formatting and comment
changes. When a cell's Python meaning changes or the match becomes ambiguous,
inspect the notebook and bind the alias again with `--overwrite`.

### Create and list views

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio view list analysis.py
```

Use `view add` to create the named view and configure the notebook when needed.
Use `view list` to print each view's name, path, and default status.

`view add` accepts `--dry-run`. Both commands accept
`--format text|json`.

A view name starts with a lowercase letter and contains lowercase letters,
digits, or hyphens. Names claimed by Marimo or Studio routes are reserved.

### Validate views

```console
uvx marimo-studio check analysis.py --view executive --runtime
```

`check` validates every configured view unless `--view` selects one. Static
validation checks templates, aliases, and value selectors. `--runtime` also
executes projected cells and resolves projected values.

### Machine output and diagnostics

Data commands accept `--format text` or `--format json`. Text is the default
and JSON is written to standard output.

Use `--diagnostics jsonl` for structured diagnostic events on standard error:

```console
uvx marimo-studio check analysis.py \
  --runtime \
  --format json \
  --diagnostics jsonl
```

```json
{
  "schema": 1,
  "event": "diagnostic",
  "command": "check",
  "severity": "info",
  "code": "view:dashboard",
  "message": "Validated 2 cell projections and 1 value selector",
  "status": "pass"
}
```

Every event contains `schema`, `event`, `command`, `severity`, `code`, and
`message`. Check events add `status`. Command failures add `exit_code`.

### Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Command completed |
| `1` | Validation completed and found failures |
| `2` | CLI syntax or option usage is invalid |
| `3` | Notebook or Studio configuration is invalid |
| `4` | A cell binding cannot be resolved |
| `6` | The installed Marimo version is incompatible |
| `7` | The notebook environment cannot be prepared |
| `130` | The command was interrupted |

Direct launch returns the exit status from the `marimo edit` process.

## Notebook configuration

Direct launch and `view add` store the default configuration in the notebook's
PEP 723 block:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
#
# [tool.marimo-studio.cells]
# summary = { ref = "cell:v3:<semantic-sha256>:<layout-sha256>:0" }
# ///
```

| Field | Type | Default | Behavior |
| --- | --- | --- | --- |
| `default` | String | Required | Selects the view served at `/` in run mode |
| `preserve_session` | Boolean | `false` | Reconnects a manual run-mode refresh to its current kernel |
| `cells` | Table | Empty | Stores aliases shared by every view |

The setup records `marimo-studio` without a version constraint. `uv` resolves
the current release. When the Studio CLI runs from a source checkout, it uses
that checkout as an editable package. Existing dependencies, indexes, and tool
settings stay in place.

Views for `analysis.py` live at:

```text
__marimo__/studio/analysis/<view-name>/
```

Every immediate child with an `index.html` becomes a view. The folder name is
also its run-mode route.

### Project configuration

A managed project can place the configuration in `pyproject.toml`:

```toml
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["marimo-studio"]

[tool.marimo-studio]
notebook = "analysis.py"
default = "dashboard"
preserve_session = false

[tool.marimo-studio.cells]
summary = { ref = "cell:v3:<semantic-sha256>:<layout-sha256>:0" }
```

`notebook` is required in project configuration and resolves relative to
`pyproject.toml`. View files remain beside the notebook under
`__marimo__/studio/`.

For an explicit notebook path, configuration resolves in this order:

1. PEP 723 metadata in the notebook
2. The nearest parent `pyproject.toml` whose configuration names that notebook

Notebook metadata wins when both sources identify the same notebook. A
conflict produces an error that names both sources.

### Source control

View directories contain authored source. Keep them in version control with
the notebook. A repository that ignores `__marimo__` can add:

```text
!**/__marimo__/
**/__marimo__/*
!**/__marimo__/studio/
!**/__marimo__/studio/**
```

The exception tracks Studio views while preserving the surrounding ignore rule
for other Marimo directories.

## View templates

Each `index.html` is a complete HTML document with one `<head>`, one `<body>`,
and one element with `id="app-shell"`.

Every `<marimo-cell>` and `mo-value` belongs inside `#app-shell`. Marimo serves
the document with the browser runtime needed by those elements.

Reference a view-owned file through its scoped route:

```html
<link
  rel="stylesheet"
  href="./_marimo-studio/views/dashboard/static/app.css"
>
```

### `<marimo-cell>`

```html
<marimo-cell name="summary"></marimo-cell>
```

`name` accepts a native cell name or configured alias. Each name can appear
once in a view.

States:

```text
connecting | loading | stale | ready | missing | error
```

The element records output MIME data in `data-output-mime` and
`data-output-mimes`.

Events:

- `marimo-cell-ready`
- `marimo-cell-updated`
- `marimo-cell-error`

### `mo-value`

```html
<span mo-value="report"></span>
<time mo-value="report.updated_at"></time>
<span mo-value="series[0].label"></span>
<span mo-value='metadata["key.with.dots"]'></span>
```

Grammar:

```text
selector  := identifier (dot-key | item)*
dot-key   := "." identifier
item      := "[" non-negative-integer "]"
           | "[" JSON-string "]"
```

Dot selection checks a mapping key, then Python attribute access. Bracket
selection uses item lookup. The root variable must have one defining cell.

The kernel resolves the complete selector and serializes the selected value.
Live reads accept up to 1,000,000 encoded bytes per value. Runtime inspection
uses a 64 KiB limit.

States:

```text
connecting | loading | stale | ready | error
```

Events:

- `marimo-value-updated`
- `marimo-value-error`

A value keeps its cached content while a new read is pending.

## Browser readiness

Wait for the current view:

```js
await window.marimoStudio.ready();
```

The promise resolves when every current cell and value has rendered content,
retained content while updating, or reached a terminal missing or error state.

The root `<html>` element publishes combined state through
`data-marimo-studio-state`:

```text
connecting | loading | ready | error
```

Document events:

- `marimo-studio:runtime-ready`
- `marimo-studio:idle`
- `marimo-studio:page-theme`

View switching and preview status use same-origin messages:

- `marimo-studio:switch-view`
- `marimo-studio:receiver-ready`
- `marimo-studio:view-ready`
- `marimo-studio:view-error`

## Loading and theming

Cell loading properties:

- `--marimo-cell-skeleton-height`
- `--marimo-cell-skeleton-color`
- `--marimo-cell-skeleton-radius`

Value loading properties:

- `--marimo-value-skeleton-width`
- `--marimo-value-skeleton-height`
- `--marimo-value-skeleton-color`
- `--marimo-value-skeleton-radius`

Cell presentation properties:

- `--marimo-cell-font`
- `--marimo-cell-heading-font`
- `--marimo-cell-monospace-font`
- `--marimo-cell-background`
- `--marimo-cell-surface`
- `--marimo-cell-foreground`
- `--marimo-cell-muted`
- `--marimo-cell-muted-foreground`
- `--marimo-cell-border`
- `--marimo-cell-border-color`
- `--marimo-cell-radius`
- `--marimo-cell-padding`
- `--marimo-cell-content-width`
- `--marimo-cell-accent`
- `--marimo-cell-accent-foreground`
- `--marimo-cell-error`

Set `data-skeleton="none"` on a cell element to suppress its first-load
skeleton.

## Server routes

Routes resolve beneath Marimo's configured `base_url`.

| Mode | Route | Behavior |
| --- | --- | --- |
| Edit | `/` | Native Marimo editor |
| Edit | `/studio/` | Editor and default view |
| Edit | `/studio/{view}/` | Editor and selected view |
| Edit | `/{view}/` | View attached to the editor session |
| Run | `/` | Default view |
| Run | `/{view}/` | Selected named view |
| Both | `/_marimo-studio/views` | Current view names and default |
| Both | `/_marimo-studio/views/{view}/config` | Browser runtime configuration |
| Both | `POST /_marimo-studio/views/{view}/values` | Reads selectors permitted by the view |
| Both | `/_marimo-studio/views/{view}/cells/{alias}` | Returns one cell element |
| Both | `/_marimo-studio/views/{view}/static/{path}` | Serves a view file |
| Edit | `/_marimo-studio/dev/events` | Streams view-list changes |
| Edit | `/_marimo-studio/views/{view}/dev/events` | Streams HTML and CSS changes |
| Both | `/_marimo-studio/assets/{path}` | Serves packaged browser assets |

Edit previews connect to the active editor kernel. Run-mode documents receive
Marimo's regular isolated browser sessions.
