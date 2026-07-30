# Reference

## Notebook configuration

The default configuration lives in the notebook's PEP 723 block:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "marimo-studio==0.1.0",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
# preserve_session = false
#
# [tool.marimo-studio.cells]
# summary = { ref = "cell:v3:<semantic-sha256>:<layout-sha256>:0" }
# ///
```

| Field | Type | Default | Contract |
| --- | --- | --- | --- |
| `default` | String | Required | View served at the notebook root in run mode |
| `preserve_session` | Boolean | `false` | Reconnect a manual run-mode reload to its current kernel |
| `cells` | Table | Empty | Shared aliases for anonymous notebook cells |

Direct launch and `view add` create notebook-local configuration when the
notebook has no Studio configuration. They set one exact `marimo-studio`
requirement to the invoked release and preserve unrelated PEP 723 data.

Views for `analysis.py` live at:

```text
__marimo__/studio/analysis/<view-name>/
```

Every immediate child with an `index.html` becomes a view. A view name starts
with a lowercase letter and contains lowercase letters, digits, or hyphens.
The folder name is also its run-mode route.

### Project configuration

A managed project can place the configuration in `pyproject.toml`:

```toml
[project]
name = "analysis"
version = "0.1.0"
dependencies = ["marimo-studio==0.1.0"]

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

1. PEP 723 metadata in the notebook.
2. The nearest parent `pyproject.toml` whose configuration names that
   notebook.

Notebook metadata wins when both sources identify the same notebook. A
conflict produces a configuration error that names both sources.

### Source control

View directories contain authored source. Add them to version control with the
notebook. A repository that ignores `__marimo__` can add:

```text
!**/__marimo__/
**/__marimo__/*
!**/__marimo__/studio/
!**/__marimo__/studio/**
```

This exception tracks Studio views while other Marimo runtime directories
remain covered by the surrounding ignore rules.

## Cell identity

A cell reference has this form:

```text
cell:v3:<semantic-sha256>:<layout-sha256>:<duplicate-occurrence>
```

The semantic digest identifies parsed Python and preserves runtime values.
Formatting and comments leave it unchanged. The occurrence distinguishes
identical cells in one notebook.

The layout digest recognizes Marimo Markdown serialization. A binding migrates
through that digest when exactly one cell matches. Several matches require an
explicit rebind.

Native Marimo cell names need no binding. `bind` records an alias for an
anonymous cell:

```console
uvx marimo-studio bind summary analysis.py --cell 12
```

Replace a changed binding explicitly:

```console
uvx marimo-studio bind summary analysis.py \
  --cell 14 \
  --overwrite
```

Alias names start with a letter and contain letters, digits, underscores, or
hyphens.

## View templates

Each `index.html` is a complete HTML document with one `<head>`, one `<body>`,
and one element with `id="app-shell"`.

Every `<marimo-cell>` and `mo-value` host must be inside `#app-shell`. Marimo
Studio inserts the runtime scripts, metadata, and hidden runtime root when it
serves the document.

Reference a view file through its scoped route:

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

`name` accepts a native cell name or configured alias. A name can appear once
in each view.

Host states:

```text
connecting | loading | stale | ready | missing | error
```

The host records output MIME data in `data-output-mime` and
`data-output-mimes`.

Host events:

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

Host states:

```text
connecting | loading | stale | ready | error
```

Host events:

- `marimo-value-updated`
- `marimo-value-error`

Transient reads retry with bounded delays. A host with a cached value retains
it while its state is `stale`.

## Browser readiness

```js
await window.marimoStudio.ready();
```

The promise resolves when every current cell and value host has rendered
content, retained stale content, or reached a terminal missing or error state.

`<html data-marimo-studio-state>` publishes:

```text
connecting | loading | ready | error
```

Document events:

- `marimo-studio:runtime-ready`
- `marimo-studio:idle`
- `marimo-studio:page-theme`

Studio uses same-origin messages for view switching and preview status:

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

Set `data-skeleton="none"` on a cell host to suppress its first-load skeleton.

## Command line

```text
marimo-studio [NOTEBOOK] [OPTIONS]
marimo-studio inspect [NOTEBOOK] [OPTIONS]
marimo-studio bind ALIAS [NOTEBOOK] --cell INDEX [OPTIONS]
marimo-studio view add NAME [NOTEBOOK] [OPTIONS]
marimo-studio view list [NOTEBOOK] [OPTIONS]
marimo-studio check [NOTEBOOK] [OPTIONS]
```

### Direct launch

```console
uvx marimo-studio analysis.py --view executive
```

| Option | Default | Contract |
| --- | --- | --- |
| `--view NAME` | Configured default | Open a named view |
| `--host HOST` | `127.0.0.1` | Bind Marimo to this host |
| `--port PORT` | `8000` | Bind Marimo to this port |
| `--base-url PATH` | Empty | Serve beneath a proxy path beginning with `/` |
| `--open / --headless` | `--open` | Control browser launch |
| `-- MARIMO_ARGS` | | Forward trailing arguments to `marimo edit` |

Studio manages Marimo's host, port, base URL, proxy, browser, and sandbox
options. Put those options before `--`.

### Data commands

| Command | Contract |
| --- | --- |
| `inspect [NOTEBOOK]` | Return static cell metadata. `--runtime` adds executed MIME and value data |
| `bind ALIAS [NOTEBOOK] --cell N` | Bind an alias to a zero-based cell index |
| `view add NAME [NOTEBOOK]` | Configure the notebook when needed and add a blank view |
| `view list [NOTEBOOK]` | Return view names, paths, and the default |
| `check [NOTEBOOK]` | Validate every view or one view selected with `--view` |

Data commands accept `--format text` or `--format json`. Text is the default.
Mutation commands also accept `--dry-run`. `bind` uses `--overwrite` to replace
an existing alias.

### Diagnostics

Data commands accept `--diagnostics jsonl` for structured events on stderr.
Command results remain on stdout.

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

Required fields are `schema`, `event`, `command`, `severity`, `code`, and
`message`. Check events include `status`. Command failures include
`exit_code`.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Command completed |
| `1` | Validation completed and found failures |
| `2` | CLI syntax or option usage is invalid |
| `3` | Notebook or Studio configuration is invalid |
| `4` | A cell binding cannot be resolved |
| `6` | The installed Marimo version is incompatible |
| `7` | The notebook environment cannot be prepared |
| `130` | The command was interrupted |

## Runtime routes

Routes resolve beneath Marimo's configured `base_url`.

| Mode | Route | Contract |
| --- | --- | --- |
| Edit | `/` | Native Marimo editor |
| Edit | `/_marimo-studio/studio/` | Editor and selected view |
| Edit | `/_marimo-studio/preview/{view}/` | View attached to the editor session |
| Run | `/` | Default view |
| Run | `/{view}/` | Selected named view |
| Both | `/_marimo-studio/views` | Current view names and default |
| Both | `/_marimo-studio/views/{view}/config` | Browser runtime configuration |
| Both | `POST /_marimo-studio/views/{view}/values` | Read selectors permitted by the view |
| Both | `/_marimo-studio/views/{view}/cells/{alias}` | Return one cell host |
| Both | `/_marimo-studio/views/{view}/static/{path}` | Serve a view file |
| Edit | `/_marimo-studio/dev/events` | Stream view-list changes |
| Edit | `/_marimo-studio/views/{view}/dev/events` | Stream HTML and CSS changes |
| Both | `/_marimo-studio/assets/{path}` | Serve packaged browser assets |

Edit previews connect as kiosk consumers to the active editor kernel. Run-mode
documents receive Marimo's regular isolated browser sessions.

Marimo owns its WebSocket, API, authentication, health, virtual file, and
notebook asset routes.
