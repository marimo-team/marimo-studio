"""Load Studio configuration and parse view templates."""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from marimo_studio._workspace.files import reject_mutable_symlinks
from marimo_studio._workspace.metadata import notebook_config
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    MARIMO_DIRECTORY,
    PYPROJECT_NAME,
    RESERVED_VIEW_NAMES,
    RUNTIME_PATTERN,
    STUDIO_DIRECTORY,
    VIEW_PATTERN,
    StudioDefinition,
    StudioWorkspace,
    View,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import CellRef


def validate_view_name(name: str) -> str:
    if not VIEW_PATTERN.fullmatch(name):
        raise ConfigurationError(
            "View names must start with a lowercase letter and contain lowercase "
            "letters, digits, or hyphens."
        )
    if name in RESERVED_VIEW_NAMES:
        raise ConfigurationError(f"View name {name!r} is reserved.")
    return name


def _runtime_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not RUNTIME_PATTERN.fullmatch(value):
        raise ConfigurationError(
            f"{field} must start with a lowercase letter and contain lowercase "
            "letters, digits, or hyphens"
        )
    return value


def _runtimes(data: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    default = _runtime_id(data.get("runtime", "server"), "runtime")
    raw = data.get("runtimes", [default])
    if not isinstance(raw, list) or not raw:
        raise ConfigurationError("runtimes must be a non-empty array")
    values = tuple(_runtime_id(value, "runtimes entries") for value in raw)
    if len(set(values)) != len(values):
        raise ConfigurationError("runtimes must not contain duplicates")
    if default not in values:
        raise ConfigurationError("runtime must be present in runtimes")
    return default, values


def read_toml(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ConfigurationError(f"Configuration is a symlink: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {path}: {error}") from error


def _pyproject_config(
    data: Mapping[str, Any],
    path: Path,
    *,
    required: bool,
) -> Mapping[str, Any] | None:
    tool = data.get("tool")
    config = tool.get("marimo-studio") if isinstance(tool, dict) else None
    if config is None:
        if required:
            raise ConfigurationError(
                f"Studio configuration not found: add [tool.marimo-studio] to {path}"
            )
        return None
    if not isinstance(config, dict):
        raise ConfigurationError(f"[tool.marimo-studio] must be a TOML table: {path}")
    return config


def _directories(start: Path) -> Iterator[Path]:
    yield start
    yield from start.parents


def _config_in(directory: Path) -> tuple[Path, Mapping[str, Any]] | None:
    pyproject = directory / PYPROJECT_NAME
    if pyproject.is_file():
        data = read_toml(pyproject)
        config = _pyproject_config(data, pyproject, required=False)
        if config is not None:
            return pyproject, config
    return None


def _project_notebook(
    config_path: Path,
    data: Mapping[str, Any],
) -> Path:
    return _path(config_path.parent, data.get("notebook"), "notebook")


def _project_for_notebook(
    notebook: Path,
) -> tuple[Path, Mapping[str, Any]] | None:
    for directory in notebook.parents:
        config_path = directory / PYPROJECT_NAME
        if not config_path.is_file():
            continue
        try:
            document = read_toml(config_path)
        except ConfigurationError:
            continue
        tool = document.get("tool")
        data = tool.get("marimo-studio") if isinstance(tool, dict) else None
        if not isinstance(data, dict):
            continue
        configured = data.get("notebook")
        if not isinstance(configured, str) or not configured.strip():
            continue
        if _project_notebook(config_path, data) == notebook:
            return config_path, data
    return None


def _notebook_configured_in(directory: Path) -> tuple[Path, Mapping[str, Any]] | None:
    configured: list[tuple[Path, Mapping[str, Any]]] = []
    for notebook in sorted(directory.glob("*.py")):
        config = notebook_config(notebook)
        if config is not None:
            configured.append((notebook.resolve(), config))
    if len(configured) > 1:
        names = ", ".join(path.name for path, _ in configured)
        raise ConfigurationError(
            f"Multiple configured notebooks found in {directory}: {names}. "
            "Pass a notebook path."
        )
    return configured[0] if configured else None


def _load_config(target: Path) -> tuple[Path, Mapping[str, Any]]:
    target = target.resolve()
    if not target.exists():
        raise ConfigurationError(f"Target does not exist: {target}")
    if target.is_file() and target.name == PYPROJECT_NAME:
        data = read_toml(target)
        config = _pyproject_config(data, target, required=True)
        assert config is not None
        return target, config
    if target.is_file() and target.suffix == ".toml":
        raise ConfigurationError(f"Expected {PYPROJECT_NAME}, received {target}")
    if target.is_file():
        inline = notebook_config(target)
        if inline is not None:
            return target, inline
        project_config = _project_for_notebook(target)
        if project_config is not None:
            return project_config
        raise ConfigurationError(
            f"No [tool.marimo-studio] configuration found for {target}. "
            f"Run `marimo-studio view add <name> {target}` to create one."
        )
    start = target if target.is_dir() else target.parent
    inline = _notebook_configured_in(start)
    for directory in _directories(start):
        found = _config_in(directory)
        if found is None:
            continue
        if inline is None:
            return found
        project_notebook = _project_notebook(found[0], found[1])
        if project_notebook == inline[0]:
            return inline
        raise ConfigurationError(
            f"{start} contains notebook configuration for {inline[0].name} "
            f"and project configuration for {project_notebook.name}. "
            "Pass a notebook path."
        )
    if inline is not None:
        return inline
    raise ConfigurationError(
        f"No Studio configuration found in {start}. Pass a notebook path to create one."
    )


def _path(base: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty path")
    return (base / value).expanduser().resolve()


def canonical_view_root(notebook: str | Path) -> Path:
    """Return the authored view directory for a notebook."""
    path = Path(notebook).expanduser().resolve()
    return path.parent / MARIMO_DIRECTORY / STUDIO_DIRECTORY / path.stem


def _discover_views(
    view_root: Path,
) -> dict[str, View]:
    if not view_root.is_dir():
        return {}
    views: dict[str, View] = {}
    for directory in sorted(view_root.iterdir(), key=lambda path: path.name):
        if not directory.is_dir() or not (directory / "index.html").is_file():
            continue
        reject_mutable_symlinks(
            view_root,
            {directory, directory / "index.html"},
        )
        validate_view_name(directory.name)
        views[directory.name] = View(directory.name, directory.resolve())
    return views


def load_studio_definition(
    target: str | Path | None = None,
) -> StudioDefinition:
    """Load the configuration that declares a Studio workspace."""
    config_path, data = _load_config(Path(target or ".").expanduser())
    config_source = "pyproject" if config_path.name == PYPROJECT_NAME else "notebook"
    notebook = (
        _project_notebook(config_path, data)
        if config_source == "pyproject"
        else config_path
    )
    view_root = canonical_view_root(notebook)
    reject_mutable_symlinks(notebook.parent, {view_root})
    default_view = data.get("default")
    if not isinstance(default_view, str):
        raise ConfigurationError("default must name a view")
    validate_view_name(default_view)
    default_runtime, runtimes = _runtimes(data)
    preserve_session = data.get("preserve_session", False)
    if not isinstance(preserve_session, bool):
        raise ConfigurationError("preserve_session must be a boolean")
    show_cell_logs = data.get("show_cell_logs", True)
    if not isinstance(show_cell_logs, bool):
        raise ConfigurationError("show_cell_logs must be a boolean")
    raw_cells = data.get("cells", {})
    if not isinstance(raw_cells, dict):
        raise ConfigurationError("cells must be a TOML table")
    cells: dict[str, CellRef] = {}
    for alias, value in raw_cells.items():
        if not isinstance(alias, str) or not ALIAS_PATTERN.fullmatch(alias):
            raise ConfigurationError(f"Invalid cell alias: {alias}")
        raw_ref = value.get("ref") if isinstance(value, dict) else None
        if not isinstance(raw_ref, str):
            raise ConfigurationError(f"Cell binding {alias} must contain a ref string")
        try:
            cells[alias] = CellRef.parse(raw_ref)
        except ValueError as error:
            raise ConfigurationError(f"Invalid binding for {alias}: {error}") from error
    return StudioDefinition(
        root=config_path.parent,
        config_path=config_path,
        config_source=config_source,
        notebook=notebook,
        view_root=view_root,
        default_view=default_view,
        default_runtime=default_runtime,
        runtimes=runtimes,
        preserve_session=preserve_session,
        cells=cells,
        show_cell_logs=show_cell_logs,
    )


def materialize_studio_workspace(
    definition: StudioDefinition,
) -> StudioWorkspace:
    """Resolve a Studio definition into its initialized workspace."""
    views = _discover_views(definition.view_root)
    return StudioWorkspace(
        root=definition.root,
        config_path=definition.config_path,
        config_source=definition.config_source,
        notebook=definition.notebook,
        view_root=definition.view_root,
        default_view=definition.default_view,
        default_runtime=definition.default_runtime,
        runtimes=definition.runtimes,
        preserve_session=definition.preserve_session,
        cells=definition.cells,
        show_cell_logs=definition.show_cell_logs,
        views=views,
    )


def load_studio(target: str | Path | None = None) -> StudioWorkspace:
    """Load an initialized Studio workspace."""
    return materialize_studio_workspace(load_studio_definition(target))


def discover_studio(notebook: str | Path) -> StudioWorkspace | None:
    """Find a presentation configured for ``notebook``."""
    notebook_path = Path(notebook).expanduser().resolve()
    if notebook_config(notebook_path) is not None:
        return load_studio(notebook_path)
    project_config = _project_for_notebook(notebook_path)
    if project_config is not None:
        return load_studio(project_config[0])
    return None


def discover_studio_definition(notebook: str | Path) -> StudioDefinition | None:
    """Find the Studio definition for a notebook."""
    notebook_path = Path(notebook).expanduser().resolve()
    if notebook_config(notebook_path) is not None:
        return load_studio_definition(notebook_path)
    project_config = _project_for_notebook(notebook_path)
    if project_config is not None:
        return load_studio_definition(project_config[0])
    return None


def editable_studio_config(document: Any) -> Any:
    return document["tool"]["marimo-studio"]
