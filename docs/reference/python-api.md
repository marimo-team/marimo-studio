---
title: Python API reference
description: Inspect Marimo notebook structure, configure integrations, and create a run-mode ASGI application.
---

# Python API reference

The public Python API inspects a notebook's static cell graph, exposes host
integration policy, and creates one configured Marimo ASGI application.

| Job                                                              | API                    |
| ---------------------------------------------------------------- | ---------------------- |
| Read cell names, definitions, dependencies, and source locations | `inspect_notebook`     |
| Build one run-mode server application                            | `create_asgi_app`      |
| Select runtime-bound projection hosts through Lens               | `LENS_TARGET_SELECTOR` |

For a regular standalone process, use Marimo's CLI:

```console
uv run --with marimo-studio \
  marimo run analysis.py \
  --sandbox \
  --headless
```

## `LENS_TARGET_SELECTOR`

`LENS_TARGET_SELECTOR` is the CSS selector for runtime-bound cell, output, and
value hosts. Pass it to Lens and compose authored page regions into the same
selector when they should also receive feedback.

```python
from marimo_lens import Lens
from marimo_studio import LENS_TARGET_SELECTOR

lens = Lens(dom_selector=f"{LENS_TARGET_SELECTOR}, #app-shell > header")
```

Studio owns this selector and the producer metadata on matching hosts. Lens
remains independent of Studio's custom elements and binding syntax.

## `inspect_notebook`

```python
inspect_notebook(
    path: str | pathlib.Path,
    *,
    include_code: bool = False,
) -> NotebookSpec
```

Compiles the notebook graph and returns a `NotebookSpec`. It leaves cell bodies
unevaluated.

```python
from marimo_studio import inspect_notebook

notebook = inspect_notebook("analysis.py")
for cell in notebook.cells:
    print(cell.index, cell.name, cell.definitions)
```

Set `include_code=True` to include each complete cell body in `CellSpec.code`.
The default leaves that field as `None`.

Raises `ConfigurationError` when the path is missing, is not a Python
notebook, or cannot be compiled by the installed Marimo version.

## `NotebookSpec`

```python
@dataclass(frozen=True)
class NotebookSpec:
    path: pathlib.Path
    cells: tuple[CellSpec, ...]
    app_config: dict[str, Any]
```

Methods:

| Method          | Result                                                                      |
| --------------- | --------------------------------------------------------------------------- |
| `by_ref()`      | Map each `CellRef` to its `CellSpec`                                        |
| `named_cells()` | Map native cell names to their `CellSpec`                                   |
| `to_dict()`     | JSON-compatible record with `schema`, `notebook`, `app_config`, and `cells` |

## `CellSpec`

Each cell record contains:

| Field                       | Shape                                                             |
| --------------------------- | ----------------------------------------------------------------- |
| `index`                     | Zero-based notebook position                                      |
| `name`                      | Native Marimo cell name or `None`                                 |
| `ref`                       | Stable `CellRef` used by Studio aliases                           |
| `runtime_id`                | Marimo cell ID for the inspected notebook                         |
| `source`                    | `SourceSpan` with start and end line and column values            |
| `preview`                   | Bounded source preview                                            |
| `definitions`, `references` | Variable-name tuples                                              |
| `upstream`, `downstream`    | Tuples of related `CellRef` values                                |
| `config`                    | `CellConfigSpec` with column, disabled, and code-visibility state |
| `has_output_expression`     | Whether the cell body ends with a displayed expression            |
| `code`                      | Complete source when `include_code=True`, otherwise `None`        |

`CellRef.parse(value)` accepts a `cell:v1:...` string or an existing `CellRef`.
`str(ref)` returns the serialized reference.

## `create_asgi_app` <Badge type="info" text="Pinned Marimo release" />

```python
create_asgi_app(
    notebook: str | pathlib.Path,
) -> ASGIApp
```

Loads the notebook's Studio definition and returns a run-mode Marimo ASGI
application. The definition can precede authored view files. The default and
named views use the same server process after the workspace is initialized.
Each browser receives its regular isolated Marimo run session.

```python
from marimo_studio import create_asgi_app

app = create_asgi_app("analysis.py")
```

The factory requires the exact Marimo release declared by the installed
`marimo-studio` package.

A definition with zero views still produces the ASGI application. Run-mode
document requests return `409` with `workspace-not-initialized`, the configured
default, and an edit-mode repair hint. Create the first view through a Marimo
edit process or `marimo-studio view add` before serving traffic.

Raises:

- `ConfigurationError` when the notebook or Studio configuration is invalid.
- `ProtocolError` when the installed Marimo source or packaged browser assets
  differ from the tagged release.

### Environment-configured application

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

## Public exports

`marimo_studio` exports:

```text
ASGIApp
CellConfigSpec
CellRef
CellSpec
LENS_TARGET_SELECTOR
NotebookSpec
SourceSpan
create_asgi_app
inspect_notebook
```

[Notebook configuration](configuration.md) defines how the application finds
views and runtime settings.
