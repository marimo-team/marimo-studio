"""Create the first or an additional view as one recoverable transaction.

View setup combines provider-owned starter files with Studio-owned notebook
configuration, provider requirements, workspace ignore rules, and
``view.toml``. The provider chooses the frontend project shape while Studio
chooses the durable manifest and notebook-to-workspace relationship.

Planning and provider work happen before the final workspace mutation. View
creation applies the notebook and complete view plan through one recoverable
file transaction. On failure it restores prior files or preserves recovery
copies when an external edit prevents rollback. A dry run returns the same plan
without changing files.
"""

from __future__ import annotations

from contextlib import ExitStack, nullcontext
from pathlib import Path

from marimo_studio._filesystem._secure_types import (
    ConditionalWriteError,
    FileIdentity,
)
from marimo_studio._filesystem.io import (
    read_file_snapshot_with_identity,
    reject_mutable_symlinks,
)
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.source_snapshot import inspect_notebook_source
from marimo_studio._views.creation_plan import (
    PreparedExistingView,
    PreparedStarter,
    SavedNotebook,
    ValidatedViewCreation,
    ViewCreationPlan,
    build_view_creation_plan,
    prepare_existing_view,
    prepare_starter,
    select_starter,
    workspace_provider_ids,
    workspace_provider_requirements,
)
from marimo_studio._views.records import Starter, ViewSetupResult
from marimo_studio._views.starter_context import starter_bindings
from marimo_studio._workspace.bindings import cell_bindings_source
from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    discover_views,
    load_studio,
    validate_view_name,
)
from marimo_studio._workspace.config_snapshot import (
    WorkspaceConfigSnapshot,
    snapshot_workspace_config,
)
from marimo_studio._workspace.generation import unconfigured_catalog_generation
from marimo_studio._workspace.metadata import configured_notebook_source
from marimo_studio._workspace.models import (
    DEFAULT_VIEW_NAME,
    StudioDefinition,
    StudioWorkspace,
)
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import (
    ConfigurationError,
    ViewExistsError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)
from marimo_studio.errors._internal import WorkspaceInitializationError
from marimo_studio.view_providers import StarterPlan
from marimo_studio.view_providers._host.requirements import (
    resolve_launch_requirements,
)


def _text_snapshot(
    path: Path,
    *,
    root: Path | None = None,
) -> tuple[str, FileIdentity]:
    payload, _mode, identity = read_file_snapshot_with_identity(path, root=root)
    try:
        return payload.decode("utf-8"), identity
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"Workspace file is not UTF-8 text: {path}") from error


def _studio_snapshot(
    notebook: Path,
) -> WorkspaceConfigSnapshot[StudioDefinition] | None:
    initial = discover_studio_definition(notebook)
    if initial is None:
        if discover_studio_definition(notebook) is not None:
            raise ConfigurationError(
                "Studio configuration changed during discovery. "
                "Run the operation again."
            )
        return None

    def reload_studio(_path: Path) -> StudioDefinition:
        current = discover_studio_definition(notebook)
        if current is None:
            raise ConfigurationError(
                "Studio configuration changed during discovery. "
                "Run the operation again."
            )
        return current

    return snapshot_workspace_config(initial, reload_studio=reload_studio)


def _require_notebook_config_identity(
    snapshot: WorkspaceConfigSnapshot[StudioDefinition] | None,
    notebook: SavedNotebook,
) -> None:
    if (
        snapshot is not None
        and snapshot.studio.uses_notebook_config
        and snapshot.config_identity != notebook.identity
    ):
        raise ConfigurationError(
            "The notebook changed while Studio read its configuration. "
            "Run the operation again."
        )


def _saved_notebook(
    path: Path,
    inspect_notebook: NotebookInspector,
) -> SavedNotebook:
    source, identity = _text_snapshot(path)
    notebook = inspect_notebook_source(
        path,
        source,
        inspect_notebook,
        include_code=True,
    )
    return SavedNotebook(notebook, source, identity)


def _reject_manifestless_view_directories(
    view_root: Path,
    view_names: tuple[str, ...],
) -> None:
    for view_name in view_names:
        directory = view_root / view_name
        manifest = directory / "view.toml"
        occupied = directory.exists() or directory.is_symlink()
        if occupied and (
            directory.is_symlink() or not manifest.is_file() or manifest.is_symlink()
        ):
            raise ViewExistsError(view_name, missing_manifest=True)


def _reject_workspace_ignore_shape(view_root: Path) -> None:
    path = view_root / ".gitignore"
    if (path.exists() or path.is_symlink()) and (
        path.is_symlink() or not path.is_file()
    ):
        raise ConfigurationError(f"Workspace ignore path is not a file: {path}")


def _validate_view_creation(
    notebook: str | Path,
    name: str | None = None,
    *,
    inspect_notebook: NotebookInspector,
    fail_if_exists: bool = False,
) -> ValidatedViewCreation:
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")
    saved_notebook = _saved_notebook(notebook_path, inspect_notebook)
    config_snapshot = _studio_snapshot(notebook_path)
    studio = config_snapshot.studio if config_snapshot is not None else None
    config_identity = (
        config_snapshot.config_identity if config_snapshot is not None else None
    )
    _require_notebook_config_identity(config_snapshot, saved_notebook)
    selected = name or (
        studio.default_view if studio is not None else DEFAULT_VIEW_NAME
    )
    validate_view_name(selected)
    view_root = (
        studio.view_root if studio is not None else canonical_view_root(notebook_path)
    )
    if fail_if_exists and (view_root / selected / "view.toml").is_file():
        raise ViewExistsError(selected)
    default_view = studio.default_view if studio is not None else selected
    workspace_root = studio.root if studio is not None else notebook_path.parent
    reject_mutable_symlinks(workspace_root, {view_root})
    _reject_workspace_ignore_shape(view_root)
    view_names = tuple(dict.fromkeys((default_view, selected)))
    _reject_manifestless_view_directories(view_root, view_names)
    new_views = tuple(
        view_name
        for view_name in view_names
        if not (view_root / view_name / "view.toml").is_file()
    )
    return ValidatedViewCreation(
        notebook_path=notebook_path,
        saved_notebook=saved_notebook,
        config_snapshot=config_snapshot,
        studio=studio,
        config_identity=config_identity,
        selected=selected,
        default_view=default_view,
        view_root=view_root,
        new_views=new_views,
    )


def _commit_view_creation_plan(plan: ViewCreationPlan) -> StudioWorkspace:
    transaction = (
        write_file_transaction(
            plan.transaction_root,
            plan.writes,
            expected=plan.expected_identities,
            claimed_directories=plan.claimed_directories,
        )
        if plan.writes
        else nullcontext()
    )
    try:
        with transaction:
            return load_studio(plan.notebook)
    except ConditionalWriteError as error:
        raise WorkspaceMutationError(
            "View creation",
            recovery=error.recovery,
            write_committed=error.committed is not None,
        ) from error


def _view_setup_result(
    plan: ViewCreationPlan,
    *,
    workspace: StudioWorkspace | None,
    dry_run: bool,
) -> ViewSetupResult:
    return ViewSetupResult(
        workspace=workspace,
        notebook=plan.notebook,
        config_path=plan.config_path,
        name=plan.name,
        root=plan.root,
        provider=plan.provider,
        documents=plan.documents,
        created=plan.created,
        updated=plan.updated,
        dry_run=dry_run,
        launch_requirements=plan.launch_requirements,
    )


def prepare_view(
    notebook: str | Path,
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    fail_if_exists: bool = False,
    expected_catalog_generation: str | None = None,
) -> ViewSetupResult:
    """Configure a notebook when needed and create a named view."""
    validated = _validate_view_creation(
        notebook,
        name,
        inspect_notebook=inspect_notebook,
        fail_if_exists=fail_if_exists,
    )
    if dry_run:
        plan = build_view_creation_plan(
            validated,
            starter=starter,
            inspect_notebook=inspect_notebook,
            dry_run=True,
        )
        return _view_setup_result(plan, workspace=None, dry_run=True)
    notebook_path = validated.notebook_path
    saved_notebook = validated.saved_notebook
    config_snapshot = validated.config_snapshot
    studio = validated.studio
    config_source = config_snapshot.source if config_snapshot is not None else None
    config_identity = validated.config_identity
    selected = validated.selected
    default_view = validated.default_view
    view_root = validated.view_root
    missing = validated.new_views
    preplanned: PreparedStarter | None = None
    prepared_existing: PreparedExistingView | None = None
    pending_starter: Starter | None = None
    plans: dict[str, StarterPlan] = {}
    if missing:
        pending_starter, provider, provider_starter = select_starter(starter)
        preplanned = prepare_starter(
            notebook_path,
            saved_notebook,
            studio,
            config_identity,
            view_root,
            default_view,
            missing,
            pending_starter,
            provider,
            provider_starter,
            inspect_notebook,
        )
        plans = preplanned.plans
    current_views = discover_views(view_root)
    if selected in current_views and selected not in missing:
        prepared_existing = prepare_existing_view(current_views[selected])
    if studio is None or studio.uses_notebook_config:
        bindings = (
            starter_bindings(saved_notebook.notebook, studio, plans.values())
            if missing
            else {}
        )
        configured_notebook_source(
            notebook_path,
            default_view,
            workspace_provider_requirements(view_root, pending_starter),
            bindings,
            source=saved_notebook.source,
        )
    elif missing:
        assert config_source is not None
        cell_bindings_source(
            studio,
            starter_bindings(saved_notebook.notebook, studio, plans.values()),
            source=config_source,
        )
    prevalidated_launch_requirements = resolve_launch_requirements(
        workspace_provider_ids(view_root, pending_starter)
    )
    with workspace_catalog_lock(view_root):
        locked_studio = discover_studio_definition(notebook_path)
        if expected_catalog_generation is not None:
            if locked_studio is None:
                current_generation = unconfigured_catalog_generation(notebook_path)
            else:
                try:
                    current_generation = load_studio(notebook_path).catalog_generation
                except WorkspaceInitializationError:
                    current_generation = locked_studio.config_generation
            if current_generation != expected_catalog_generation:
                raise WorkspaceGenerationConflictError()
        locked_selected = name or (
            locked_studio.default_view
            if locked_studio is not None
            else DEFAULT_VIEW_NAME
        )
        validate_view_name(locked_selected)
        locked_default = (
            locked_studio.default_view if locked_studio is not None else locked_selected
        )
        _reject_manifestless_view_directories(
            view_root,
            tuple(dict.fromkeys((locked_default, locked_selected))),
        )
        if fail_if_exists and (view_root / locked_selected / "view.toml").is_file():
            raise ViewExistsError(locked_selected)
        with ExitStack() as locks:
            for view_name in sorted({locked_default, locked_selected}):
                locks.enter_context(view_mutation_lock(view_root, view_name))
            locked = _validate_view_creation(
                notebook_path,
                name,
                inspect_notebook=inspect_notebook,
                fail_if_exists=fail_if_exists,
            )
            plan = build_view_creation_plan(
                locked,
                starter=starter,
                inspect_notebook=inspect_notebook,
                preplanned=preplanned,
                prepared_existing=prepared_existing,
                prevalidated_launch_requirements=prevalidated_launch_requirements,
            )
            workspace = _commit_view_creation_plan(plan)
            return _view_setup_result(plan, workspace=workspace, dry_run=False)
