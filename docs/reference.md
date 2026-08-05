# Commands and configuration

Studio authoring commands create views, inspect cells, record aliases, and
validate projections. Marimo's `edit` and `run` commands own the server. Start
with [Create your first view](getting-started.md) for a complete workflow.

## Commands

```text
marimo-studio inspect [OPTIONS] [NOTEBOOK]
marimo-studio bind [OPTIONS] ALIAS [NOTEBOOK]
marimo-studio view add [OPTIONS] NAME [NOTEBOOK]
marimo-studio view list [OPTIONS] [NOTEBOOK]
marimo-studio check [OPTIONS] [NOTEBOOK]
marimo-studio export [OPTIONS] [NOTEBOOK]
```

Pass a notebook path when creating the first view. Later commands can discover
the configured notebook from its directory or project.

### `inspect`

```console
uvx marimo-studio inspect analysis.py --display
```

Compiles the notebook graph and prints one record per cell.

| Option                | Behavior                                                                |
| --------------------- | ----------------------------------------------------------------------- |
| `--display`           | Keep cells with a final displayed expression                            |
| `--include-code`      | Include each complete cell body                                         |
| `--runtime`           | Execute the notebook and include MIME output and JSON-compatible values |
| `--limit N`           | Return at most `N` cell records                                         |
| `--format text\|json` | Select human or machine output                                          |

Static inspection leaves cell bodies unevaluated. Runtime inspection can
perform the file, network, database, and data access used by the notebook.

### `bind`

```console
uvx marimo-studio bind summary analysis.py --cell 12
```

Records a stable alias for the zero-based cell index.

| Option                | Behavior                                             |
| --------------------- | ---------------------------------------------------- |
| `--cell INDEX`        | Select the zero-based notebook cell                  |
| `--dry-run`           | Report the binding and leave configuration unchanged |
| `--overwrite`         | Replace an existing alias                            |
| `--format text\|json` | Select human or machine output                       |

Native Marimo cell names need no binding. Alias names start with a letter and
contain letters, digits, underscores, or hyphens.

An alias follows its cell across formatting and comment changes. Reinspect and
bind with `--overwrite` after the cell's Python meaning changes or the match
becomes ambiguous.

### `view add` and `view list`

```console
uvx marimo-studio view add executive analysis.py
uvx marimo-studio view list analysis.py
```

`view add` creates the view and configures the notebook when needed. It accepts
`--dry-run`. Both commands accept `--format text|json`.

A view name starts with a lowercase letter and contains lowercase letters,
digits, or hyphens. Names claimed by Marimo or Studio routes are reserved.

### `check`

```console
uvx marimo-studio check analysis.py --view executive --runtime
```

Static checks validate templates, aliases, and value selectors. `--runtime`
also executes projected cells and resolves projected values. Omit `--view` to
check every configured view.

### `export`

```console
uvx marimo-studio export analysis.py \
  --view executive \
  --output dist/executive
```

Writes the selected view as a static WebAssembly site. The configured default
view is selected when `--view` is absent.

| Option                | Behavior                                |
| --------------------- | --------------------------------------- |
| `--output DIR`        | Write the complete static site to `DIR` |
| `--view NAME`         | Export a named view                     |
| `--force`             | Replace an existing output directory    |
| `--format text\|json` | Select human or machine output          |

The command validates every projected cell and value before writing. A JSON
result includes the selected view, runtime, output directory, entry point, and
file count. Serve the output over HTTP so the browser can load worker modules
and runtime assets.

### Machine output

Data commands accept `--format text` or `--format json`. Text is the default.
JSON results go to standard output.

Use `--diagnostics jsonl` for one diagnostic event per standard-error line:

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
  "severity": "error",
  "code": "cell-not-found",
  "message": "Cell 'summary' is not defined in the notebook.",
  "status": "fail",
  "details": {
    "view": "dashboard",
    "projection": "cell",
    "target": "summary",
    "source": {
      "path": "/workspace/__marimo__/studio/analysis/dashboard/index.html",
      "line": 24,
      "column": 7
    },
    "hint": "Name a notebook cell, change the projection target, or remove it from the view."
  }
}
```

Every event has `schema`, `event`, `command`, `severity`, `code`, and
`message`. Check events add `status`. Projection findings add the view, target,
source location, and repair hint. Command failures add `exit_code`.

Runtime cell failures point to the notebook definition. Runtime value failures
point to the `mo-value` host and include the defining notebook cell.

### Exit codes

|  Code | Meaning                                      |
| ----: | -------------------------------------------- |
|   `0` | Command completed                            |
|   `1` | Validation found failures                    |
|   `2` | CLI syntax or option usage is invalid        |
|   `3` | Notebook or Studio configuration is invalid  |
|   `4` | A cell binding cannot be resolved            |
|   `6` | The installed Marimo version is incompatible |
|   `7` | The notebook environment cannot be prepared  |
| `130` | The command was interrupted                  |

## Notebook configuration

`view add` stores notebook-local configuration in the PEP 723 block:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "marimo-studio",
# ]
#
# [tool.marimo-studio]
# default = "dashboard"
# runtime = "server"
# runtimes = ["server", "wasm"]
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# summary = { ref = "cell:v1:<semantic-sha256>:<layout-sha256>:0" }
# ///
```

| Field              | Type     | Default     | Behavior                                                  |
| ------------------ | -------- | ----------- | --------------------------------------------------------- |
| `default`          | String   | Required    | Select the view served at `/` in run mode                 |
| `runtime`          | String   | `"server"`  | Select the runtime used when a view URL has no override   |
| `runtimes`         | String[] | `[runtime]` | Permit runtimes in run mode                               |
| `preserve_session` | Boolean  | `false`     | Reconnect a manual server-runtime refresh to its kernel   |
| `show_cell_logs`   | Boolean  | `true`      | Render cell `stdout` and `stderr` in projected cell hosts |
| `cells`            | Table    | Empty       | Store aliases shared by every view                        |

Set `show_cell_logs = false` when projected views should exclude text written
through `print`, Python logging, and warnings. Primary cell results, media,
input prompts, and structured Marimo errors continue to render.

Edit mode offers every runtime bundled with Studio. Run mode exposes the
entries in `runtimes`. Enabling `wasm` sends a derived copy of the notebook
source to the browser so Pyodide can execute it. Studio leaves the saved
notebook unchanged and omits Studio-specific and uv metadata from that copy.

In the Studio workspace, JSON-compatible values from native `mo.ui` controls
synchronize between the editor and a WebAssembly preview. Each kernel reruns
its own reactive graph. Matching requires each cell to construct the same
native controls in the same order in both runtimes. Anywidgets remain
interactive in each runtime, and their comm state stays with the runtime that
created the model.

The dependency entry is `marimo-studio` with no version constraint. Existing
dependencies, indexes, and tool settings remain in place.

Views for `analysis.py` live at:

```text
__marimo__/studio/analysis/<view-name>/
```

Every immediate child with an `index.html` is a view. The folder name is also
its run-mode route.

### Project configuration

A managed project can use `pyproject.toml`:

```toml
[project]
name = "analysis"
version = "0.1.0"
dependencies = ["marimo-studio"]

[tool.marimo-studio]
notebook = "analysis.py"
default = "dashboard"
runtime = "server"
runtimes = ["server", "wasm"]
preserve_session = false
show_cell_logs = false

[tool.marimo-studio.cells]
summary = { ref = "cell:v1:<semantic-sha256>:<layout-sha256>:0" }
```

`notebook` is required in project configuration and resolves relative to
`pyproject.toml`. View files remain beside the notebook under
`__marimo__/studio/`.

For an explicit notebook path, Studio resolves configuration in this order:

1. PEP 723 metadata in the notebook
2. The nearest parent `pyproject.toml` that names the notebook

Notebook metadata wins when both sources identify the same notebook. A
conflict reports both sources.

[Create and manage views](views.md#keep-views-with-the-notebook) covers source
control for `__marimo__/studio/`.

## View templates

Each `index.html` is a complete document with one `<head>`, one `<body>`, and
one `#app-shell`. Every `<marimo-cell>` and `mo-value` host belongs inside that
shell.

New views contain two authored files:

```text
index.html
app.css
```

`app.css` starts with a `/* THEME */` section for semantic variables and a
`/* APP */` section for page rules. Studio loads its foundation and generated
Wind4 utilities in named cascade layers. The linked `app.css` uses the regular
unlayered cascade, so its rules take precedence.

Write Wind4 utilities directly on elements. Studio scans the initial
`#app-shell`, HTML refreshes, and nodes inserted later by HTMX. The stable
shortcuts are `studio-view`, `studio-card`, `studio-button`, and
`studio-eyebrow`. Semantic color utilities resolve through the theme variables
in `app.css`, including `bg-background`, `text-foreground`, `bg-card`,
`border-border`, `text-primary`, and `ring-ring`.

Use the same Iconify element and icon names as Marimo:

```html
<iconify-icon icon="lucide:leaf" aria-hidden="true"></iconify-icon>
```

Iconify downloads icon data when the element first requests a name. Deployments
that restrict outbound requests need to allow the Iconify API. Use an inline
SVG when a static export must render fully offline.

Reference view files with ordinary relative URLs:

```html
<link rel="stylesheet" href="app.css" />
<script type="module" src="app.js"></script>
```

An external editor can add modules, images, fonts, and nested asset folders to
the view directory. Relative imports in JavaScript and `url(...)` references in
CSS resolve from their source file. Studio reloads a scripted document after
an HTML or module change so the browser evaluates its module graph as a page.

The top-level paths `_marimo-studio`, `@file`, `public`, and
`public-files-sw.js` belong to Studio or Marimo. Place authored assets under
other names such as `scripts/`, `images/`, and `fonts/`. Every other regular
file in the view directory is available from the served page and is included
in a static export, so keep credentials outside that directory.

Generated utilities require native CSS `@scope` support. Studio shows a style
diagnostic when the browser lacks that feature while `app.css`, authored
scripts, and notebook outputs continue to run.

### `<marimo-cell>`

```html
<marimo-cell name="summary"></marimo-cell>
```

`name` accepts a native cell name or configured alias. Each name can appear
once per view.

States:

```text
connecting | loading | stale | ready | missing | error
```

The element records MIME data in `data-output-mime` and
`data-output-mimes`. An unresolved cell records
`data-marimo-diagnostic-code`, `data-marimo-diagnostic-message`, and
`data-marimo-diagnostic-hint`.

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

Live reads accept up to 1,000,000 encoded bytes per value. Runtime inspection
uses a 64 KiB limit.

States:

```text
connecting | loading | stale | ready | error
```

Events:

- `marimo-value-updated`
- `marimo-value-error`

A value keeps cached content while a new kernel read is pending. An unresolved
selector clears the value, records the diagnostic attributes, and exposes an
accessible description.

## Browser readiness

```js
await window.marimoStudio.ready();
const diagnostics = window.marimoStudio.diagnostics();
```

`ready()` resolves after every current cell and value has content, retained
content during an update, or a terminal diagnostic. It stays pending during an
HTML, CSS, or notebook refresh.

`diagnostics()` returns a snapshot of projection, presentation, host, and
runtime failures. Projection paths are relative to the notebook in browser
responses. CLI diagnostics keep absolute paths.

The root `<html>` element publishes combined state in
`data-marimo-studio-state`:

```text
connecting | loading | ready | error
```

Document events:

- `marimo-studio:runtime-ready`
- `marimo-studio:idle`
- `marimo-studio:page-theme`

Same-origin preview messages:

- `marimo-studio:navigate-view`
- `marimo-studio:switch-view`
- `marimo-studio:receiver-ready`
- `marimo-studio:view-ready`
- `marimo-studio:view-diagnostics`
- `marimo-studio:view-sync-pending`
- `marimo-studio:view-error`

## Loading and theming

| Scope           | Properties                                                                                                                               |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Cell skeleton   | `--marimo-cell-skeleton-height`, `--marimo-cell-skeleton-color`, `--marimo-cell-skeleton-radius`                                         |
| Value skeleton  | `--marimo-value-skeleton-width`, `--marimo-value-skeleton-height`, `--marimo-value-skeleton-color`, `--marimo-value-skeleton-radius`     |
| Cell typography | `--marimo-cell-font`, `--marimo-cell-heading-font`, `--marimo-cell-monospace-font`                                                       |
| Cell surface    | `--marimo-cell-background`, `--marimo-cell-surface`, `--marimo-cell-foreground`, `--marimo-cell-muted`, `--marimo-cell-muted-foreground` |
| Cell frame      | `--marimo-cell-border`, `--marimo-cell-border-color`, `--marimo-cell-radius`, `--marimo-cell-padding`, `--marimo-cell-content-width`     |
| Cell accent     | `--marimo-cell-accent`, `--marimo-cell-accent-foreground`, `--marimo-cell-error`                                                         |

Set `data-skeleton="none"` on a cell to suppress its first-load skeleton.

## Server routes

Routes resolve beneath Marimo's configured `base_url`.

| Mode | Route                                            | Behavior                                    |
| ---- | ------------------------------------------------ | ------------------------------------------- |
| Edit | `/`                                              | Open the default Studio workspace           |
| Edit | `/?file={file-key}`                              | Open Marimo's native editor inside Studio   |
| Edit | `/studio/`                                       | Open the editor and default view            |
| Edit | `/studio/{view}/`                                | Open the editor and selected view           |
| Edit | `/{view}/`                                       | Attach a view to the editor session         |
| Run  | `/`                                              | Serve the default view                      |
| Run  | `/{view}/`                                       | Serve a named view                          |
| Both | `/{view}/{path}`                                 | Serve a file from the named view            |
| Both | `/{view}/_marimo-studio/{path}`                  | Resolve a view-relative Studio request      |
| Both | `/{view}/@file/{path}`                           | Resolve a view-relative Marimo virtual file |
| Both | `/{view}/public/{path}`                          | Resolve a view-relative notebook asset      |
| Both | `/_marimo-studio/views`                          | List current views and the default          |
| Edit | `POST /_marimo-studio/views`                     | Create a view                               |
| Edit | `DELETE /_marimo-studio/views/{view}`            | Delete a view                               |
| Both | `/_marimo-studio/views/{view}/config`            | Read runtime configuration                  |
| Both | `GET /_marimo-studio/views/{view}/source/{file}` | Read a view source file with an ETag        |
| Edit | `PUT /_marimo-studio/views/{view}/source/{file}` | Replace source with an `If-Match` revision  |
| Both | `POST /_marimo-studio/views/{view}/values`       | Read selectors permitted by the view        |
| Both | `/_marimo-studio/views/{view}/cells/{alias}`     | Create one cell host                        |
| Edit | `/_marimo-studio/dev/events`                     | Stream view-list changes                    |
| Edit | `/_marimo-studio/views/{view}/dev/events`        | Stream view source changes                  |
| Both | `/_marimo-studio/assets/{path}`                  | Serve packaged browser assets               |

Edit previews connect to the active editor kernel. Run-mode documents receive
Marimo's regular isolated browser sessions.

Studio sends Marimo's server token on mutation requests. Source writes preserve
UTF-8 content and line endings. A stale `If-Match` returns `412` with the
current source revision. `{file}` accepts `index.html` or `app.css`.
