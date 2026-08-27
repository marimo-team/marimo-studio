---
title: Python API
description: Create a run-mode application or inspect a saved Marimo notebook from Python.
---

# Python API

The root package exposes two operations and their result types. Use the
[Agent API](agent-api.md) for notebook-bound view authoring.

## `create_asgi_app`

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("analysis.py")
```

```python
create_asgi_app(notebook: str | Path) -> ASGIApp
```

Returns the Marimo run-mode ASGI application for one configured notebook. The
application serves the default and named views through Studio's validated
publication routes. Its ASGI lifespan opens the notebook's Studio adapters,
then closes active notebook sessions and Studio-owned tasks during shutdown.

The notebook must be saved and configured. A configured notebook with no view
returns a structured `409 workspace-not-initialized` response that names the
default view to create.

### Environment-configured application

`marimo_studio.asgi:app` reads the notebook path from
`MARIMO_STUDIO_NOTEBOOK`:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app \
  --host 127.0.0.1 \
  --port 8000
```

Install the notebook dependencies in the application-server environment.

## `inspect_notebook`

```python
from marimo_studio import inspect_notebook

notebook = inspect_notebook("analysis.py", include_code=True)
```

```python
inspect_notebook(
    path: str | Path,
    *,
    include_code: bool = False,
) -> NotebookSpec
```

Compiles the saved notebook and returns its cell inventory, source spans,
definitions, references, and dependency relationships. Cell bodies remain
unevaluated.

## Public records

| Record           | Fields and methods                                                                 |
| ---------------- | ---------------------------------------------------------------------------------- |
| `ASGIApp`        | Async `scope`, `receive`, and `send` callable                                      |
| `CellRef`        | `fingerprint`, `layout_fingerprint`, `occurrence`, `parse()`, and `str()`          |
| `SourceSpan`     | `start_line`, `end_line`, `start_column`, and `end_column`                         |
| `CellConfigSpec` | `column`, `disabled`, and `hide_code`                                              |
| `CellSpec`       | Identity, source, code digest, preview, definitions, references, graph, and config |
| `NotebookSpec`   | `path`, `cells`, `app_config`, `by_ref()`, `named_cells()`, and `to_dict()`        |

`inspect_notebook(..., include_code=True)` includes `CellSpec.code`. The default
keeps code out of each record while retaining its digest and preview.

`LENS_TARGET_SELECTOR` identifies mounted Studio result hosts for tools that
integrate with the rendered page.

View-provider contracts live in `marimo_studio.view_providers` and are
documented in the [Frontend extension API](provider-api.md).
