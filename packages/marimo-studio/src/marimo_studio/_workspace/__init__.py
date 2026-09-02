"""Load and update the Studio workspace attached to a notebook.

Workspace configuration can live in the notebook's PEP 723 metadata or in
``[tool.marimo-studio]`` inside ``pyproject.toml``. It selects the notebook,
default view, permitted runtimes, session policy, cell aliases, and related
execution settings. Each named view stores its provider and explicit options
in its own ``view.toml``.

A materialized workspace contains at least one valid view and a valid default.
Server, editor, export, validation, CLI, and agent callers load the same model.
Cross-process locks and recoverable file transactions keep view creation,
configuration changes, and removal coherent.
"""

from marimo_studio._workspace.config import discover_studio as discover_studio
from marimo_studio._workspace.config import load_studio as load_studio
