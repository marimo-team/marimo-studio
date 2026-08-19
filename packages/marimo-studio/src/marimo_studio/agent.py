"""Use Marimo Studio from code mode."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from textwrap import indent
from types import ModuleType

import agent_plugins

from marimo_studio._runtime_limits import DEFAULT_RUNTIME_TIMEOUT
from marimo_studio.activation import ViewActivationResult
from marimo_studio.analysis import DEFAULT_BROWSER_TIMEOUT, AnalysisReport
from marimo_studio.checks import CheckReport
from marimo_studio.inspect import InspectionResult
from marimo_studio.overview import StudioOverview
from marimo_studio.workspace import BindingResult, ViewSetupResult

_DISTRIBUTION_NAME = "marimo-studio"
_SKILL_NAME = "marimo-studio"


def agent_plugin() -> agent_plugins.Plugin:
    """Return the Agent Plugin installed with this Studio version."""
    return agent_plugins.locate(_DISTRIBUTION_NAME)


def _agent_skill(plugin: agent_plugins.Plugin) -> agent_plugins.Skill:
    for skill in plugin.skills:
        if skill.path.name == _SKILL_NAME:
            return skill
    raise agent_plugins.AgentPluginError(
        "The marimo-studio Agent Plugin has no marimo-studio skill. "
        "Reinstall marimo-studio."
    )


def agent_skill() -> agent_plugins.Skill:
    """Return Studio's packaged Agent Skill."""
    return _agent_skill(agent_plugin())


def _module_help(summary: str) -> str:
    plugin = agent_plugin()
    skill = _agent_skill(plugin)
    tree = indent(plugin.tree(max_depth=3, max_files=50), "    ")
    return f"""{summary}

Start with the active notebook context:

    import marimo._code_mode as cm
    import marimo_studio.agent as studio

    ctx = cm.get_context()
    workspace = studio.overview(ctx)
    inspection = studio.inspect(ctx, include_code=True)
    view = studio.ensure_view(ctx, "dashboard")
    activation = await studio.activate_view(ctx, view.name)

Activate the returned view before substantial authoring. The starter document
makes the user's request visible, and later saves show progress in the active
preview.

The installed Agent Plugin carries the complete authoring workflow and the
resources that match this Studio version:

{tree}

Read the Studio skill instructions at:

    {skill / "SKILL.md"}

Traverse the same resources programmatically:

    resources = studio.agent_plugin()
    skill = studio.agent_skill()
    print(resources)
    print(skill.body)
"""


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
    display: bool = False,
    limit: int | None = None,
) -> InspectionResult:
    """Read the cells and their relationships from the saved notebook.

    Set ``include_code`` to include complete cell bodies. This compiles the
    saved notebook to understand its structure and does not run its code.
    """
    from marimo_studio.inspect import inspect_notebook_result

    return inspect_notebook_result(
        notebook_path(context),
        include_code=include_code,
        output_expressions=display,
        limit=limit,
    )


def overview(context: object) -> StudioOverview:
    """Describe Studio configuration and views for the active notebook."""
    from marimo_studio.overview import overview as inspect_overview

    return inspect_overview(notebook_path(context))


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
) -> CheckReport:
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
    view: str | None = None,
    browser_timeout: float = DEFAULT_BROWSER_TIMEOUT,
    runtime_timeout: float = DEFAULT_RUNTIME_TIMEOUT,
    require_browser: bool = True,
) -> AnalysisReport:
    """Validate view sources, notebook projections, and rendered readiness.

    Browser analysis requires ``view`` for the active Studio view. Activate
    that view in a separate code-mode call before analyzing it. Set
    ``require_browser=False`` to run static and runtime validation across every
    configured view when ``view`` is absent. ``browser_timeout`` controls how
    long Studio waits for the browser to report the saved view revision. Code
    mode runs the analysis through its attached Studio server.
    ``runtime_timeout`` bounds isolated notebook execution.

    Raises:
        CapabilityInputError: A request field or timeout is invalid.
        AgentRequestError: The attached server or browser cannot complete the
            analysis.
    """
    from marimo_studio._agent_client import request_analysis
    from marimo_studio._composition import create_tooling_adapters
    from marimo_studio._workspace import load_studio
    from marimo_studio.analysis import AnalysisRequest

    notebook = notebook_path(context)
    request = AnalysisRequest(
        view=view,
        browser_timeout=browser_timeout,
        runtime_timeout=runtime_timeout,
        require_browser=require_browser,
    )
    request.require_focused_view()
    workspace = load_studio(notebook)
    connection = create_tooling_adapters().code_mode.connection()
    return await request_analysis(
        connection,
        workspace.notebook,
        request,
    )


async def activate_view(
    context: object,
    name: str,
) -> ViewActivationResult:
    """Select a named view and its Build layout in the current browser.

    Call this as soon as ``ensure_view`` returns, including for a starter view,
    so the user sees the requested view while authoring continues.

    Reactivating the current view reloads its prepared preview runtimes. First
    view setup opens Studio around the existing native editor and preserves the
    code-mode call until the Build workspace acknowledges the transition.
    """
    from marimo_studio._composition import create_tooling_adapters
    from marimo_studio._workspace import load_studio
    from marimo_studio.activation import activate_view as activate

    workspace = load_studio(notebook_path(context))
    return await activate(
        workspace,
        create_tooling_adapters().code_mode.connection(),
        name,
    )


__all__ = [
    "activate_view",
    "agent_plugin",
    "agent_skill",
    "analyze",
    "bind",
    "check",
    "ensure_view",
    "inspect",
    "notebook_path",
    "overview",
]


class _AgentModule(ModuleType):
    @property
    def __doc__(self) -> str | None:  # pyrefly: ignore [bad-override]
        summary = self.__dict__.get("__doc__")
        return _module_help(summary) if isinstance(summary, str) else None

    @__doc__.setter
    def __doc__(self, value: str | None) -> None:
        self.__dict__["__doc__"] = value


sys.modules[__name__].__class__ = _AgentModule
