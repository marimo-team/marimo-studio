# Python API

The Python API exposes static notebook inspection and a configured Marimo ASGI
application.

| Job | API |
| --- | --- |
| Discover cells, names, definitions, and dependencies | `inspect_notebook` |
| Build one run-mode ASGI application | `create_asgi_app` |

For command-line deployment, run the notebook through Marimo:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless
```

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

Compiles the notebook graph and returns a `NotebookSpec`. Inspection leaves
cell bodies unevaluated.

Each `CellSpec` contains:

- Its zero-based index and native Marimo name
- A stable `CellRef`
- Source location and optional complete code
- Defined and referenced variables
- Upstream and downstream cell references
- Marimo cell configuration
- Whether the cell ends with a displayed expression

Set `include_code=True` to include each complete cell body. The default keeps
code out of the returned object.

Raises `ConfigurationError` when the path is missing, is not a Python
notebook, or cannot be compiled by the installed Marimo version.

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

Loads the notebook's Studio configuration and returns a run-mode Marimo ASGI
application. The default and named views use the same Marimo server process.
Each browser receives its regular isolated run session.

The factory requires Marimo 0.23.16 or newer.

Raises:

- `ConfigurationError` when the notebook or Studio configuration is invalid
- `ProtocolError` when the installed Marimo version is older than 0.23.16

### Run the environment-configured app

`marimo_studio.asgi:app` reads the notebook path from
`MARIMO_STUDIO_NOTEBOOK`:

```console
MARIMO_STUDIO_NOTEBOOK=/srv/analysis/analysis.py \
  uvicorn marimo_studio.asgi:app \
  --host 0.0.0.0 \
  --port 8000
```

Install the notebook dependencies in the Uvicorn environment before starting
the server.

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
