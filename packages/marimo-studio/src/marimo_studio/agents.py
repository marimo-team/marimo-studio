"""Turn the active Marimo notebook into a custom web page.

Marimo Studio lets one notebook power dashboards, reports, and focused tools.
Calculations, data, controls, plots, tables, downloads, and anywidgets remain in
notebook cells. A custom view chooses what to show and arranges it with HTML and
CSS. Marimo keeps the page connected to the running notebook, so controls and
dependent outputs continue to update.

One notebook can have several named views for different audiences. Each view
has its own ``index.html`` and ``app.css`` while sharing the notebook's Python
calculations and interactive controls.

Use this module from Marimo code mode. The context tells Studio which open
notebook to work with:

    import marimo._code_mode as cm
    import marimo_studio.agents as studio

    ctx = cm.get_context()
    notebook = studio.inspect(ctx, include_code=True)
    setup = studio.ensure_view(ctx, "dashboard")

``studio.inspect`` returns the saved cells in notebook order, including their
positions, names, code, and variable relationships. ``studio.ensure_view``
creates the named view when needed. A new view starts with every notebook cell
in order, so the page has working content before it is customized.

The two editable files are stored in ``setup.root``:

    index_path = setup.root / "index.html"
    css_path = setup.root / "app.css"

Read the current files before changing them so edits from the browser or
another editor are preserved. Keep Python calculations in notebook cells and
page structure, wording, and styling in these files. ``index.html`` is a
complete HTML document with one ``#app-shell`` element.

Place a notebook cell's complete output in the page with ``<marimo-cell>``.
Show a JSON-compatible Python value, such as a string, number, list, or
dictionary, as text with ``mo-value``:

    <marimo-cell name="revenue-chart"></marimo-cell>
    <strong mo-value="summary.total"></strong>

Cell output keeps its Marimo behavior, including controls, tables, plots,
downloads, and anywidgets. A value reference starts with a Python variable and
can select nested attributes, mapping keys, or list items.

Use a cell's existing name when it is clear. Give an unnamed cell a memorable
reference by binding a name to its zero-based notebook position:

    studio.bind(ctx, "revenue-chart", 4)

Check the custom page after editing its HTML or CSS:

    results = studio.check(ctx, view_name="dashboard")
    failures = [result for result in results if result.status == "fail"]

Each result has a ``pass``, ``warn``, or ``fail`` status and points to the
affected cell, Python value, or view file. Saved HTML and CSS changes refresh
the custom page. Notebook edits update the outputs that depend on them.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marimo_studio._workspace.models import BindingResult, ViewSetupResult
    from marimo_studio.types import CheckResult, NotebookSpec


def notebook_path(context: object) -> Path:
    """Return the saved notebook path exposed by a code-mode context.

    Raises:
        TypeError: ``context`` does not expose a globals mapping.
        RuntimeError: The active notebook has not been saved.
        FileNotFoundError: The saved notebook file is unavailable.
    """
    namespace = getattr(context, "globals", None)
    if not isinstance(namespace, Mapping):
        raise TypeError("context must expose a globals mapping")

    filename = namespace.get("__file__")
    if not isinstance(filename, (str, Path)) or not str(filename):
        raise RuntimeError("Save the active notebook before using Marimo Studio.")

    notebook = Path(filename).expanduser().resolve()
    if not notebook.is_file():
        raise FileNotFoundError(f"The active notebook file is unavailable: {notebook}")
    return notebook


def inspect(
    context: object,
    *,
    include_code: bool = False,
) -> NotebookSpec:
    """Read the cells and their relationships from the saved notebook.

    Set ``include_code`` to include complete cell bodies. This compiles the
    saved notebook to understand its structure and does not run its code.
    """
    from marimo_studio import inspect_notebook

    return inspect_notebook(notebook_path(context), include_code=include_code)


def ensure_view(
    context: object,
    name: str | None = None,
    *,
    dry_run: bool = False,
) -> ViewSetupResult:
    """Create a named custom view or return its existing files.

    The default name is the configured view or ``dashboard``. A new view gets
    an ``index.html`` and ``app.css`` containing every notebook cell in order.
    Studio may also add its configuration to the notebook. Set ``dry_run`` to
    return the planned paths without writing them.
    """
    from marimo_studio.workspace import ensure_view as ensure

    return ensure(notebook_path(context), name, dry_run=dry_run)


def bind(
    context: object,
    alias: str,
    cell_index: int,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Give a notebook cell a stable name for use in custom HTML.

    ``cell_index`` is the cell's zero-based notebook position. Set
    ``overwrite`` when the name should point to a different cell. Set
    ``dry_run`` to return the planned change without updating configuration.
    """
    from marimo_studio._workspace import load_studio
    from marimo_studio.workspace import bind_cell

    return bind_cell(
        load_studio(notebook_path(context)),
        alias,
        cell_index,
        dry_run=dry_run,
        overwrite=overwrite,
    )


def check(
    context: object,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Check that custom pages reference cells and values in the notebook.

    Pass ``view_name`` to check one named view. The default checks every view.
    Each result has a ``pass``, ``warn``, or ``fail`` status. This check reads
    and compiles the saved notebook and does not run its code.
    """
    from marimo_studio._workspace import load_studio
    from marimo_studio.checks import check_studio

    return check_studio(
        load_studio(notebook_path(context)),
        view_name=view_name,
    )


__all__ = ["bind", "check", "ensure_view", "inspect", "notebook_path"]
