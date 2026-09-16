"""Turn supported configuration files into Studio definitions and workspaces.

The loader resolves an unambiguous notebook target, reads PEP 723 metadata or
``[tool.marimo-studio]`` from ``pyproject.toml``, validates names and settings,
and discovers contained view projects through ``view.toml``. Discovery can
return ``None`` for an unconfigured notebook. A ``StudioDefinition`` can
represent a configured notebook that still needs its first view, while
materialization requires at least one valid view and a valid default.

This is the single parsing and target-selection path used by Studio's command,
server, agent, build, validation, and export entry points.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._filesystem.io import (
    read_file_snapshot_with_identity,
    reject_mutable_symlinks,
)
from marimo_studio._filesystem.paths import (
    PORTABLE_PATH_COMPONENT_MAX_BYTES,
    validate_portable_path_component,
)
from marimo_studio._notebook.records import CellRef
from marimo_studio._workspace.generation import (
    directory_generation,
    view_generation,
    workspace_catalog_generation,
)
from marimo_studio._workspace.metadata import (
    _provider_dependency_requirements,
    notebook_config,
    notebook_config_source,
)
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    MARIMO_DIRECTORY,
    PYPROJECT_NAME,
    RESERVED_VIEW_NAMES,
    STUDIO_DIRECTORY,
    VIEW_NAME_MAX_BYTES,
    VIEW_PATTERN,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio._workspace.project_manifest import load_view_project
from marimo_studio._workspace.toml import parse_toml, read_toml
from marimo_studio._workspace.view_owners import reconcile_view_owners
from marimo_studio.errors import ConfigurationError, WorkspaceGenerationConflictError
from marimo_studio.errors._internal import WorkspaceInitializationError
from marimo_studio.view_providers import ViewProject

_COMMON_CONFIG_FIELDS = frozenset(
    {
        "cells",
        "default",
        "preserve_session",
        "runtime",
        "runtimes",
        "show_cell_logs",
    }
)
_SUPPORTED_RUNTIMES = frozenset({"server", "wasm", "zero-python"})
_NOTEBOOK_STEM_MAX_BYTES = PORTABLE_PATH_COMPONENT_MAX_BYTES - len(".py")
_WORKSPACE_MATERIALIZATION_LIMIT = 8


def _reject_unknown_config_fields(
    data: Mapping[str, Any],
    path: Path,
    *,
    project: bool,
) -> None:
    supported = _COMMON_CONFIG_FIELDS | (
        {"notebook"} if project else {"provider_dependencies"}
    )
    unknown = sorted(set(data) - supported)
    if unknown:
        raise ConfigurationError(
            f"Unsupported [tool.marimo-studio] field {unknown[0]!r}: {path}"
        )
    if not project:
        _provider_dependency_requirements(data)


def validate_view_name(name: str) -> str:
    if not VIEW_PATTERN.fullmatch(name):
        raise ConfigurationError(
            "View names must start with a lowercase letter and contain lowercase "
            "letters, digits, or hyphens."
        )
    if name in RESERVED_VIEW_NAMES:
        raise ConfigurationError(f"View name {name!r} is reserved.")
    try:
        validate_portable_path_component(
            name,
            field="View name",
            max_bytes=VIEW_NAME_MAX_BYTES,
        )
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    return name


def _runtime_id(value: object, field: str) -> str:
    if not isinstance(value, str) or value not in _SUPPORTED_RUNTIMES:
        raise ConfigurationError(
            f"{field} must be one of: {', '.join(sorted(_SUPPORTED_RUNTIMES))}"
        )
    return value


def _runtimes(data: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    default = _runtime_id(data.get("runtime", "server"), "runtime")
    if default == "zero-python":
        raise ConfigurationError("runtime must be one of: server, wasm")
    raw = data.get("runtimes", [default])
    if not isinstance(raw, list) or not raw:
        raise ConfigurationError("runtimes must be a non-empty array")
    values = tuple(_runtime_id(value, "runtimes entries") for value in raw)
    if len(set(values)) != len(values):
        raise ConfigurationError("runtimes must not contain duplicates")
    if default not in values:
        raise ConfigurationError("runtime must be present in runtimes")
    return default, values


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
    _reject_unknown_config_fields(config, path, project=True)
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
    root = config_path.parent.resolve()
    notebook = _path(root, data.get("notebook"), "notebook")
    try:
        notebook.relative_to(root)
    except ValueError as error:
        raise ConfigurationError(
            f"notebook must stay inside the project directory: {config_path}"
        ) from error
    return notebook


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
        _reject_unknown_config_fields(data, config_path, project=True)
        configured = data.get("notebook")
        if not isinstance(configured, str) or not configured.strip():
            continue
        if _project_notebook(config_path, data) == notebook:
            return config_path, data
    return None


def _configuration_for_notebook(
    notebook: Path,
) -> tuple[Path, Mapping[str, Any]] | None:
    try:
        inline = notebook_config(notebook)
        project = _project_for_notebook(notebook)
    except FileNotFoundError as error:
        raise WorkspaceGenerationConflictError() from error
    if inline is not None and project is not None:
        raise ConfigurationError(
            f"Studio configuration for {notebook.name} appears in both "
            f"{notebook} and {project[0]}. Keep one configuration source."
        )
    if inline is not None:
        return notebook, inline
    return project


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
        notebook = _project_notebook(target, config)
        if notebook_config(notebook) is not None:
            raise ConfigurationError(
                f"Studio configuration for {notebook.name} appears in both "
                f"{notebook} and {target}. Keep one configuration source."
            )
        return target, config
    if target.is_file() and target.suffix == ".toml":
        raise ConfigurationError(f"Expected {PYPROJECT_NAME}, received {target}")
    if target.is_file():
        configured = _configuration_for_notebook(target)
        if configured is not None:
            return configured
        raise ConfigurationError(
            f"No [tool.marimo-studio] configuration found for {target}. "
            "Run `marimo-studio view create dashboard "
            f"--target {target}` to create one."
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
            raise ConfigurationError(
                f"Studio configuration for {inline[0].name} appears in both "
                f"{inline[0]} and {found[0]}. Keep one configuration source."
            )
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
    try:
        validate_portable_path_component(
            path.stem,
            field="Notebook filename stem",
            max_bytes=_NOTEBOOK_STEM_MAX_BYTES,
        )
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    return path.parent / MARIMO_DIRECTORY / STUDIO_DIRECTORY / path.stem


def discover_views(
    view_root: Path,
) -> dict[str, ViewProject]:
    if not view_root.is_dir():
        return {}
    views: dict[str, ViewProject] = {}
    for directory in sorted(view_root.iterdir(), key=lambda path: path.name):
        if directory.is_symlink():
            reject_mutable_symlinks(view_root, {directory})
        if not directory.is_dir() or not (directory / "view.toml").is_file():
            continue
        reject_mutable_symlinks(
            view_root,
            {directory, directory / "view.toml"},
        )
        validate_view_name(directory.name)
        try:
            project = load_view_project(directory)
        except FileNotFoundError:
            # A concurrent view removal can finish between inventory and load.
            continue
        except ConfigurationError:
            if not directory.is_dir() or not (directory / "view.toml").is_file():
                continue
            raise
        views[directory.name] = project
    return views


def _studio_definition(
    config_path: Path,
    data: Mapping[str, Any],
) -> StudioDefinition:
    config_source = "pyproject" if config_path.name == PYPROJECT_NAME else "notebook"
    _reject_unknown_config_fields(
        data,
        config_path,
        project=config_source == "pyproject",
    )
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
        if not isinstance(value, dict):
            raise ConfigurationError(f"Cell binding {alias} must be a TOML table")
        unknown_binding_fields = sorted(set(value) - {"ref"})
        if unknown_binding_fields:
            raise ConfigurationError(
                f"Unsupported field {unknown_binding_fields[0]!r} "
                f"in cell binding {alias!r}"
            )
        raw_ref = value.get("ref")
        if not isinstance(raw_ref, str):
            raise ConfigurationError(f"Cell binding {alias} must contain a ref string")
        try:
            cells[alias] = CellRef.parse(raw_ref)
        except ValueError as error:
            raise ConfigurationError(f"Invalid binding for {alias}: {error}") from error
    config_generation = hashlib.sha256(
        repr(
            (
                config_path.parent,
                config_source,
                notebook,
                view_root,
                default_view,
                default_runtime,
                runtimes,
                preserve_session,
                show_cell_logs,
                tuple(sorted(cells.items())),
                _provider_dependency_requirements(data),
            )
        ).encode("utf-8")
    ).hexdigest()
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
        config_generation=config_generation,
    )


def studio_definition_from_source(config_path: Path, source: str) -> StudioDefinition:
    """Decode a Studio definition from one captured configuration source."""
    if config_path.name == PYPROJECT_NAME:
        data = _pyproject_config(
            parse_toml(source, config_path),
            config_path,
            required=True,
        )
    else:
        data = notebook_config_source(config_path, source)
    if data is None:
        raise ConfigurationError(
            f"Studio configuration not found in captured source: {config_path}"
        )
    return _studio_definition(config_path, data)


def load_studio_definition(
    target: str | Path | None = None,
) -> StudioDefinition:
    """Load the configuration that declares a Studio workspace."""
    try:
        config_path, _data = _load_config(Path(target or ".").expanduser())
    except FileNotFoundError as error:
        raise WorkspaceGenerationConflictError() from error
    try:
        payload, _mode, identity = read_file_snapshot_with_identity(
            config_path,
            root=config_path.parent,
        )
        source = payload.decode("utf-8")
        definition = studio_definition_from_source(config_path, source)
        _confirmed, _confirmed_mode, confirmed_identity = (
            read_file_snapshot_with_identity(
                config_path,
                root=config_path.parent,
            )
        )
    except FileNotFoundError as error:
        raise WorkspaceGenerationConflictError() from error
    except UnicodeDecodeError as error:
        raise ConfigurationError(
            f"Workspace file is not UTF-8 text: {config_path}"
        ) from error
    if confirmed_identity != identity:
        raise ConfigurationError(
            "Studio configuration changed while it was loaded. Run the operation again."
        )
    return definition


def materialize_studio_workspace(
    definition: StudioDefinition,
) -> StudioWorkspace:
    """Resolve a Studio definition into its initialized workspace."""
    views = discover_views(definition.view_root)
    try:
        owner_names = reconcile_view_owners(
            definition.view_root,
            set(views),
            refresh_names=lambda: set(discover_views(definition.view_root)),
        )
    except (ConditionalWriteError, FileNotFoundError) as error:
        raise WorkspaceGenerationConflictError() from error
    if owner_names != set(views):
        views = discover_views(definition.view_root)
        if set(views) != owner_names:
            raise WorkspaceGenerationConflictError()
    if not views:
        raise WorkspaceInitializationError(definition.default_view)
    try:
        view_generations = {
            name: view_generation(project) for name, project in views.items()
        }
        root_generation = directory_generation(definition.view_root)
    except FileNotFoundError as error:
        raise WorkspaceGenerationConflictError() from error
    catalog_generation = workspace_catalog_generation(
        definition,
        views,
        view_generations,
        root_generation,
    )
    if discover_views(definition.view_root) != views:
        raise WorkspaceGenerationConflictError()
    try:
        generation_changed = any(
            view_generation(project) != view_generations[name]
            for name, project in views.items()
        )
    except FileNotFoundError as error:
        raise WorkspaceGenerationConflictError() from error
    if generation_changed:
        raise WorkspaceGenerationConflictError()
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
        config_generation=definition.config_generation,
        views=views,
        view_generations=view_generations,
        catalog_generation=catalog_generation,
    )


def materialize_studio_workspace_after_conflict(
    definition: StudioDefinition,
) -> StudioWorkspace:
    """Resolve a stable workspace while owning its catalog mutation barrier."""
    with workspace_catalog_lock(definition.view_root):
        conflict: WorkspaceGenerationConflictError | None = None
        for _attempt in range(_WORKSPACE_MATERIALIZATION_LIMIT):
            try:
                return materialize_studio_workspace(definition)
            except WorkspaceGenerationConflictError as error:
                conflict = error
        if conflict is None:
            raise RuntimeError("Workspace materialization made no attempts")
        raise conflict


def load_studio(target: str | Path | None = None) -> StudioWorkspace:
    """Load an initialized Studio workspace."""
    return materialize_studio_workspace(load_studio_definition(target))


def discover_studio(notebook: str | Path) -> StudioWorkspace | None:
    """Find a presentation configured for ``notebook``."""
    notebook_path = Path(notebook).expanduser().resolve()
    configured = _configuration_for_notebook(notebook_path)
    return load_studio(configured[0]) if configured is not None else None


def discover_studio_definition(notebook: str | Path) -> StudioDefinition | None:
    """Find the Studio definition for a notebook."""
    notebook_path = Path(notebook).expanduser().resolve()
    configured = _configuration_for_notebook(notebook_path)
    return load_studio_definition(configured[0]) if configured is not None else None


def editable_studio_config(document: Any) -> Any:
    return document["tool"]["marimo-studio"]
