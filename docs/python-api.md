# Python API

## `inspect_notebook`

```python
from marimo_studio import inspect_notebook

notebook = inspect_notebook("analysis.py")
for cell in notebook.cells:
    print(cell.index, cell.name, cell.definitions, cell.ref)
```

```python
inspect_notebook(
    path: str | pathlib.Path,
    *,
    include_code: bool = False,
) -> NotebookSpec
```

Compiles the notebook graph and returns cell references, runtime IDs, source
spans, definitions, dependencies, configuration, and final output-expression
status. Cell bodies remain unevaluated.

`include_code=True` adds each complete cell body to the result.

Raises `ConfigurationError` when the path or notebook is invalid.

## `create_asgi_app`

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("analysis.py")
```

```python
create_asgi_app(
    notebook: str | pathlib.Path,
) -> ASGIApp
```

Loads one configured notebook and builds Marimo's programmatic run-mode ASGI
application. The default and named view routes share Marimo's notebook runtime.

The factory validates the installed Marimo version before constructing the
application. It raises `ConfigurationError` for invalid Studio configuration
and `ProtocolError` for an incompatible Marimo version.

Run the environment-configured entry point with Uvicorn:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app \
  --host 0.0.0.0 \
  --port 8000
```

`MARIMO_STUDIO_NOTEBOOK` points to the configured notebook. Install its
dependencies in the Uvicorn environment before starting the server.

The canonical deployment command remains:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless
```

## Public types

`marimo_studio` exports:

```text
ASGIApp
CellConfigSpec
CellRef
CellSpec
NotebookSpec
SourceSpan
create_asgi_app
inspect_notebook
```
