"""Use Marimo Studio from code mode."""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from pathlib import Path
from textwrap import indent
from types import ModuleType

import agent_plugins

from marimo_studio._runtime_limits import (
    DEFAULT_RUNTIME_TIMEOUT,
    MAX_RUNTIME_TIMEOUT,
)
from marimo_studio._workspace.models import BindingResult, ViewSetupResult
from marimo_studio.agent_models import AnalysisReport, ViewActivationResult
from marimo_studio.types import CheckResult, NotebookSpec

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
    import marimo_studio.agents as studio

    ctx = cm.get_context()
    notebook = studio.inspect(ctx, include_code=True)
    view = studio.ensure_view(ctx, "dashboard")

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
    from marimo_studio._composition import create_tooling_adapters
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
        create_tooling_adapters().code_mode.connection(),
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
    from marimo_studio._composition import create_tooling_adapters
    from marimo_studio._workspace import load_studio
    from marimo_studio.errors import ConfigurationError

    workspace = load_studio(notebook_path(context))
    if name not in workspace.views:
        available = ", ".join(workspace.views)
        raise ConfigurationError(
            f"Unknown view {name!r}. Available views: {available}."
        )
    return await request_view_activation(
        create_tooling_adapters().code_mode.connection(),
        workspace.notebook,
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
