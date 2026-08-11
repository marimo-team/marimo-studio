"""Turn the active Marimo notebook into a custom web page.

Marimo Studio lets one notebook power dashboards, reports, and focused tools.
Keep notebook cells focused on computation, analytical context, data access,
domain rules, controls, and reusable rich outputs. Put page structure, display
copy, responsive layout, and visual styling in the Studio view. Use the UnoCSS
Wind4 vocabulary with Tailwind 4 syntax in ``index.html`` for ordinary
presentation. Put custom keyframes and CSS rules that utilities cannot express
in ``app.css``.

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
another editor are preserved. ``index.html`` is a complete HTML document with
one ``#app-shell`` element.

Place a notebook cell's complete output in the page with ``<marimo-cell>``.
Render one Python object's native Marimo representation with
``<marimo-output>``. Show a JSON-compatible value, such as a string, number,
list, or dictionary, as text with ``mo-value``:

    <marimo-cell name="analysis"></marimo-cell>
    <marimo-output value="revenue_chart"></marimo-output>
    <strong mo-value="summary.total"></strong>

Cell and rich-object output keep their Marimo behavior, including controls,
tables, plots, downloads, and anywidgets. A value reference starts with a
Python variable and can select nested attributes, mapping keys, or list items.

Use a cell's existing name when it is clear. Give an unnamed cell a memorable
reference by binding a name to its zero-based notebook position:

    studio.bind(ctx, "revenue-chart", 4)

Select a newly created view in the open Studio workspace:

    await studio.activate_view(ctx, "dashboard")

When the notebook gained its first Studio view during the current native
editor session, ``activate_view`` reloads that page into Studio after the
agent call finishes. Later activations use Studio's in-place view transition.

Analyze the custom page after editing its HTML or CSS:

    report = await studio.analyze(ctx, view_name="dashboard")
    if not report.handoff_ready:
        for action in report.actions:
            print(action.advice)

``studio.analyze`` runs static and isolated runtime validation, then asks the
session-bound Studio browser for fresh evidence from the captured source
revision. Fix every error and rerun it. Hand off the view only when
``report.handoff_ready`` is true.

Use the lower-level static check when notebook execution is intentionally out
of scope:

    results = studio.check(ctx, view_name="dashboard")
    failures = [result for result in results if result.status == "fail"]

Each result has a ``pass``, ``warn``, or ``fail`` status and points to the
affected projection or view file. Saved HTML and CSS changes refresh the custom
page. Notebook edits update the outputs that depend on them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

from marimo_studio._runtime_limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    MAX_RUNTIME_TIMEOUT,
)
from marimo_studio._workspace.models import BindingResult, ViewSetupResult
from marimo_studio.agent_models import AnalysisReport, ViewActivationResult
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
    """Check that custom pages reference notebook cells and values.

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


async def analyze(
    context: object,
    *,
    view_name: str | None = None,
    timeout: float = 10.0,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    require_browser: bool = True,
) -> AnalysisReport:
    """Validate view sources, notebook projections, and rendered readiness.

    Browser analysis requires ``view_name`` for the active Studio view. Activate
    that view in a separate code-mode call before analyzing it. Set
    ``require_browser=False`` to run static and runtime validation across every
    configured view when ``view_name`` is absent. ``timeout`` controls how long
    Studio waits for the browser to report the saved view revision. Code mode
    runs the analysis through its attached Studio server. ``runtime_timeout``
    bounds isolated notebook execution.

    Raises:
        ValueError: A timeout is outside its supported range, or browser
            analysis has no named view.
    """
    from marimo_studio._agent_client import request_analysis
    from marimo_studio._compat.code_mode import code_mode_connection
    from marimo_studio._workspace import load_studio

    if not math.isfinite(timeout) or not 0 <= timeout <= 20:
        raise ValueError("timeout must be a finite number between 0 and 20 seconds")
    if (
        not math.isfinite(runtime_timeout)
        or not 0 <= runtime_timeout <= MAX_RUNTIME_TIMEOUT
    ):
        raise ValueError(
            "runtime_timeout must be a finite number between 0 and "
            f"{MAX_RUNTIME_TIMEOUT:g} seconds"
        )
    if require_browser and view_name is None:
        raise ValueError(
            "Code-mode browser analysis requires view_name. Activate that view "
            "in one code-mode call, then analyze it in the next call."
        )
    workspace = load_studio(notebook_path(context))
    return await request_analysis(
        code_mode_connection(),
        workspace.notebook,
        view_name=view_name,
        timeout=timeout,
        runtime_timeout=runtime_timeout,
        require_browser=require_browser,
    )


async def activate_view(
    context: object,
    name: str,
) -> ViewActivationResult:
    """Select a named view in the current browser workspace.

    An active Studio workspace uses its normal in-place transition. A native
    editor reloads into Studio when this call follows the first view setup.
    The reload waits for the code-mode result before navigating.
    """
    from marimo_studio._agent_client import request_view_activation
    from marimo_studio._compat.code_mode import code_mode_connection
    from marimo_studio._workspace import load_studio
    from marimo_studio.errors import ConfigurationError

    workspace = load_studio(notebook_path(context))
    if name not in workspace.views:
        available = ", ".join(workspace.views)
        raise ConfigurationError(
            f"Unknown view {name!r}. Available views: {available}."
        )
    return await request_view_activation(
        code_mode_connection(),
        workspace.notebook,
        name,
    )


__all__ = [
    "activate_view",
    "analyze",
    "bind",
    "check",
    "ensure_view",
    "inspect",
    "notebook_path",
]
