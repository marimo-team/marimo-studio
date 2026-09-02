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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.inputs import (
    ProjectInputState,
    project_input_state,
    project_revision_snapshot,
)
from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._filesystem.io import (
    read_file_snapshot_with_identity,
    reject_mutable_symlinks,
)
from marimo_studio._filesystem.secure import FileIdentity
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.records import NotebookSpec
from marimo_studio._notebook.source_snapshot import inspect_notebook_source
from marimo_studio._views.catalog import resolve_starter
from marimo_studio._views.inspection import (
    inspect_view_project_sync,
)
from marimo_studio._views.records import Starter, ViewSetupResult
from marimo_studio._views.starter_context import (
    starter_bindings,
    starter_context,
)
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
from marimo_studio._workspace.metadata import configured_notebook_source
from marimo_studio._workspace.models import StudioDefinition
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio._workspace.view_owners import view_owner_transition
from marimo_studio.errors import (
    ConfigurationError,
    ViewExistsError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)
from marimo_studio.errors._internal import WorkspaceInitializationError
from marimo_studio.view_providers import (
    ProjectInspection,
    ProviderStarter,
    StarterPlan,
    ViewProject,
    ViewProvider,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.package_policy import DEFAULT_STARTER_ID
from marimo_studio.view_providers._host.requirements import (
    resolve_launch_requirements,
)

_WORKSPACE_IGNORE_RULES = ("/.locks/", "*/.artifacts/")


@dataclass(frozen=True)
class _PreparedExistingView:
    project: ViewProject
    inspection: ProjectInspection
    input_state: ProjectInputState


@dataclass(frozen=True)
class _SavedNotebook:
    notebook: NotebookSpec
    source: str
    identity: FileIdentity


@dataclass(frozen=True)
class _PreparedStarter:
    starter: Starter
    provider: ViewProvider
    provider_starter: ProviderStarter
    observed_studio: StudioDefinition | None
    observed_config_identity: FileIdentity | None
    observed_notebook: NotebookSpec
    planned_notebook: NotebookSpec
    planned_source: str
    plans: dict[str, StarterPlan]


def _prepare_existing_view(project: ViewProject) -> _PreparedExistingView:
    inspection = inspect_view_project_sync(project)
    provider = provider_registry().get(project.provider)
    snapshot = project_revision_snapshot(
        project,
        inspection,
        provider.provenance(inspection),
    )
    return _PreparedExistingView(project, inspection, snapshot.state)


def _workspace_ignore_source(source: str) -> str:
    present = {line.strip() for line in source.splitlines()}
    missing = tuple(rule for rule in _WORKSPACE_IGNORE_RULES if rule not in present)
    if not missing:
        return source
    prefix = source if not source or source.endswith("\n") else f"{source}\n"
    return prefix + "".join(f"{rule}\n" for rule in missing)


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


def _optional_text_snapshot(
    path: Path,
    *,
    root: Path | None = None,
) -> tuple[str, FileIdentity | None]:
    try:
        return _text_snapshot(path, root=root)
    except FileNotFoundError:
        return "", None


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
    notebook: _SavedNotebook,
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
) -> _SavedNotebook:
    source, identity = _text_snapshot(path)
    notebook = inspect_notebook_source(
        path,
        source,
        inspect_notebook,
        include_code=True,
    )
    return _SavedNotebook(notebook, source, identity)


def _select_starter(
    value: str | Starter | None,
) -> tuple[Starter, ViewProvider, ProviderStarter]:
    identity = value.id if isinstance(value, Starter) else value or DEFAULT_STARTER_ID
    starter, provider, provider_starter = resolve_starter(identity)
    if not starter.availability.available:
        reason = starter.availability.reason or "The provider is unavailable."
        action = starter.availability.action
        detail = f" {action}" if action is not None else ""
        raise ConfigurationError(
            f"Starter {identity!r} is unavailable: {reason}{detail}"
        )
    return starter, provider, provider_starter


def _workspace_provider_ids(
    view_root: Path,
    starter: Starter | None,
) -> tuple[str, ...]:
    provider_ids = {project.provider for project in discover_views(view_root).values()}
    if starter is not None:
        provider_ids.add(starter.provider)
    return tuple(sorted(provider_ids))


def _workspace_provider_requirements(
    view_root: Path,
    starter: Starter | None,
) -> tuple[str, ...]:
    registry = provider_registry()
    return tuple(
        registry.get(provider_id).requirement
        for provider_id in _workspace_provider_ids(view_root, starter)
    )


def _provider_plans(
    provider: ViewProvider,
    starter: ProviderStarter,
    notebook: NotebookSpec,
    studio: StudioDefinition | None,
    view_names: tuple[str, ...],
) -> dict[str, StarterPlan]:
    return {
        view_name: provider.create(
            starter,
            starter_context(notebook, studio, view_name),
        )
        for view_name in view_names
    }


def _prepare_starter(
    notebook_path: Path,
    saved: _SavedNotebook,
    studio: StudioDefinition | None,
    config_identity: FileIdentity | None,
    view_root: Path,
    default_view: str,
    view_names: tuple[str, ...],
    starter: Starter,
    provider: ViewProvider,
    provider_starter: ProviderStarter,
    inspect_notebook: NotebookInspector,
) -> _PreparedStarter:
    initial = _provider_plans(
        provider,
        provider_starter,
        saved.notebook,
        studio,
        view_names,
    )
    if studio is not None and not studio.uses_notebook_config:
        return _PreparedStarter(
            starter,
            provider,
            provider_starter,
            studio,
            config_identity,
            saved.notebook,
            saved.notebook,
            saved.source,
            initial,
        )

    bindings = starter_bindings(saved.notebook, studio, initial.values())
    configured = configured_notebook_source(
        notebook_path,
        default_view,
        _workspace_provider_requirements(view_root, starter),
        bindings,
        source=saved.source,
    )
    if configured == saved.source:
        return _PreparedStarter(
            starter,
            provider,
            provider_starter,
            studio,
            config_identity,
            saved.notebook,
            saved.notebook,
            saved.source,
            initial,
        )

    planned_notebook = inspect_notebook_source(
        notebook_path,
        configured,
        inspect_notebook,
        include_code=True,
    )
    planned = _provider_plans(
        provider,
        provider_starter,
        planned_notebook,
        studio,
        view_names,
    )
    if any(
        planned[view_name].cell_targets != initial[view_name].cell_targets
        for view_name in view_names
    ):
        raise ConfigurationError(
            "Starter cell selection changed after notebook configuration was "
            "planned. Run the operation again."
        )
    final_bindings = starter_bindings(planned_notebook, studio, planned.values())
    final_source = configured_notebook_source(
        notebook_path,
        default_view,
        _workspace_provider_requirements(view_root, starter),
        final_bindings,
        source=saved.source,
    )
    if final_source != configured:
        raise ConfigurationError(
            "Starter configuration changed after provider planning. "
            "Run the operation again."
        )
    return _PreparedStarter(
        starter,
        provider,
        provider_starter,
        studio,
        config_identity,
        saved.notebook,
        planned_notebook,
        final_source,
        planned,
    )


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


def _prepare_view_locked(
    notebook: str | Path,
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    preplanned: _PreparedStarter | None = None,
    prepared_existing: _PreparedExistingView | None = None,
    prevalidated_launch_requirements: tuple[str, ...] | None = None,
    fail_if_exists: bool = False,
) -> ViewSetupResult:
    """Configure a notebook when needed and create a named view."""
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
    selected = name or (studio.default_view if studio is not None else "dashboard")
    validate_view_name(selected)
    if (
        fail_if_exists
        and (canonical_view_root(notebook_path) / selected / "view.toml").is_file()
    ):
        raise ViewExistsError(selected)
    default_view = studio.default_view if studio is not None else selected
    view_root = canonical_view_root(notebook_path)
    reject_mutable_symlinks(notebook_path.parent, {view_root})
    _reject_workspace_ignore_shape(view_root)
    view_names = tuple(dict.fromkeys((default_view, selected)))
    _reject_manifestless_view_directories(view_root, view_names)
    new_views = tuple(
        view_name
        for view_name in view_names
        if not (view_root / view_name / "view.toml").is_file()
    )
    plans: dict[str, StarterPlan] = {}
    notebook_snapshot: NotebookSpec | None = None
    provider_starter: ProviderStarter | None
    if new_views:
        if preplanned is None:
            if not dry_run:
                raise ConfigurationError(
                    "The view catalog changed before starter planning completed. "
                    "Run the operation again."
                )
            selected_starter, provider, provider_starter = _select_starter(starter)
            prepared = _prepare_starter(
                notebook_path,
                saved_notebook,
                studio,
                config_identity,
                view_root,
                default_view,
                new_views,
                selected_starter,
                provider,
                provider_starter,
                inspect_notebook,
            )
        else:
            prepared = preplanned
            current_revision = saved_notebook.notebook.revision
            if current_revision not in {
                prepared.observed_notebook.revision,
                prepared.planned_notebook.revision,
            }:
                raise ConfigurationError(
                    "The notebook changed while starter files were prepared. "
                    "Run the operation again."
                )
            studio_matches = (
                studio == prepared.observed_studio
                and config_identity == prepared.observed_config_identity
            )
            expected_notebook_transition = (
                (
                    prepared.observed_studio is None
                    or prepared.observed_studio.uses_notebook_config
                )
                and studio is not None
                and studio.uses_notebook_config
                and current_revision == prepared.planned_notebook.revision
                and saved_notebook.source == prepared.planned_source
            )
            if not studio_matches and not expected_notebook_transition:
                if (
                    prepared.observed_studio is None
                    and studio is not None
                    and studio.uses_notebook_config
                ):
                    prepared = _prepare_starter(
                        notebook_path,
                        saved_notebook,
                        studio,
                        config_identity,
                        view_root,
                        default_view,
                        new_views,
                        prepared.starter,
                        prepared.provider,
                        prepared.provider_starter,
                        inspect_notebook,
                    )
                else:
                    raise ConfigurationError(
                        "Studio configuration changed while starter files were "
                        "prepared. Run the operation again."
                    )
        selected_starter = prepared.starter
        provider = prepared.provider
        provider_starter = prepared.provider_starter
        plans = prepared.plans
        notebook_snapshot = prepared.planned_notebook
    else:
        selected_starter = None
        provider = None
        provider_starter = None
    provider_requirements: tuple[str, ...] = ()
    if studio is None or studio.uses_notebook_config:
        provider_requirements = _workspace_provider_requirements(
            view_root,
            selected_starter,
        )
    launch_requirements = resolve_launch_requirements(
        _workspace_provider_ids(view_root, selected_starter)
    )
    if (
        prevalidated_launch_requirements is not None
        and launch_requirements != prevalidated_launch_requirements
    ):
        raise ConfigurationError(
            "View provider requirements changed before creation. "
            "Run the operation again."
        )

    if any(view_name not in plans for view_name in new_views):
        raise ConfigurationError(
            "The view catalog changed while starter files were prepared. "
            "Run the operation again."
        )
    bindings = (
        starter_bindings(
            notebook_snapshot,
            studio,
            (plans[view_name] for view_name in new_views),
        )
        if notebook_snapshot is not None
        else {}
    )
    writes: dict[Path, str | bytes] = {}
    configuration_write: tuple[Path, str] | None = None
    manifests: dict[Path, str] = {}
    expected: dict[Path, FileIdentity | None] = {}
    if studio is None or studio.uses_notebook_config:
        notebook_source = saved_notebook.source
        notebook_identity = saved_notebook.identity
        expected[notebook_path] = notebook_identity
        configured = configured_notebook_source(
            notebook_path,
            default_view,
            provider_requirements,
            bindings,
            source=notebook_source,
        )
        if notebook_snapshot is not None:
            assert saved_notebook is not None
            prospective = (
                saved_notebook.notebook
                if configured == notebook_source
                else inspect_notebook_source(
                    notebook_path,
                    configured,
                    inspect_notebook,
                    include_code=True,
                )
            )
            if prospective.revision != notebook_snapshot.revision:
                raise ConfigurationError(
                    "Notebook configuration changed while starter files were "
                    "prepared. Run the operation again."
                )
        if configured != notebook_source:
            configuration_write = (notebook_path, configured)
        config_path = notebook_path
        transaction_root = notebook_path.parent
    else:
        config_path = studio.config_path
        transaction_root = studio.root
        if notebook_snapshot is not None:
            notebook_identity = saved_notebook.identity
            expected[notebook_path] = notebook_identity
        assert config_snapshot is not None
        current_config = config_snapshot.source
        expected.update(config_snapshot.expected_identities)
        configured = cell_bindings_source(
            studio,
            bindings,
            source=current_config,
        )
        if configured != current_config:
            configuration_write = (config_path, configured)

    workspace_ignore = view_root / ".gitignore"
    current_ignore, ignore_identity = _optional_text_snapshot(workspace_ignore)
    expected[workspace_ignore] = ignore_identity
    ignore_source = _workspace_ignore_source(current_ignore)
    if ignore_source != current_ignore:
        writes[workspace_ignore] = ignore_source

    planned_documents: dict[str, tuple[Path, ...]] = {}
    claimed_directories: dict[Path, tuple[PurePosixPath, ...]] = {}
    for view_name in new_views:
        assert selected_starter is not None
        assert provider is not None
        assert provider_starter is not None
        plan = plans.get(view_name)
        if plan is None:
            raise ConfigurationError(
                "The view catalog changed while starter files were prepared. "
                "Run the operation again."
            )
        project_root = view_root / view_name
        claimed_directories[project_root] = (
            PurePosixPath("view.toml"),
            *plan.files.keys(),
        )
        planned_documents[view_name] = (
            project_root / "view.toml",
            *(project_root / relative for relative in selected_starter.documents),
        )
        manifest = project_root / "view.toml"
        expected[manifest] = None
        for relative, payload in plan.files.items():
            path = project_root / relative
            expected[path] = None
            writes[path] = payload
        manifests[manifest] = encode_view_manifest(selected_starter.provider)
        owner_path, owner_source, owner_identity = view_owner_transition(
            view_root,
            view_name,
            present=True,
        )
        expected[owner_path] = owner_identity
        writes[owner_path] = owner_source

    if studio is None:
        writes.update(manifests)
        if configuration_write is not None:
            writes[configuration_write[0]] = configuration_write[1]
    else:
        if configuration_write is not None:
            writes[configuration_write[0]] = configuration_write[1]
        writes.update(manifests)

    if selected_starter is not None and selected in planned_documents:
        selected_documents = planned_documents.get(selected, ())
        provider_id = selected_starter.provider
    elif prepared_existing is not None:
        project = discover_views(view_root).get(selected)
        if (
            project != prepared_existing.project
            or project is None
            or project_input_state(
                project,
                prepared_existing.inspection,
            )
            != prepared_existing.input_state
        ):
            raise ConfigurationError(
                "The selected view changed while its provider documents were "
                "inspected. Run the operation again."
            )
        selected_documents = (
            project.manifest,
            *(
                project.root / item.path
                for item in prepared_existing.inspection.editor_documents
            ),
        )
        provider_id = project.provider
    elif preplanned is not None and selected in preplanned.plans:
        project = discover_views(view_root).get(selected)
        planned_starter = preplanned.starter
        if project is None or project.provider != planned_starter.provider:
            raise ConfigurationError(
                "The selected view changed while starter files were prepared. "
                "Run the operation again."
            )
        selected_documents = (
            project.manifest,
            *(project.root / path for path in planned_starter.documents),
        )
        provider_id = project.provider
    elif dry_run:
        project = discover_views(view_root).get(selected)
        if project is None:
            raise ConfigurationError(
                f"View {selected!r} changed while its source plan was prepared. "
                "Run the operation again."
            )
        inspection = inspect_view_project_sync(project)
        selected_documents = (
            project.manifest,
            *(project.root / item.path for item in inspection.editor_documents),
        )
        provider_id = project.provider
    else:
        raise ConfigurationError(
            "The selected view changed while its provider documents were inspected. "
            "Run the operation again."
        )

    created = tuple(sorted(path for path in writes if not path.exists()))
    updated = tuple(sorted(path for path in writes if path.exists()))
    workspace = None
    if not dry_run:
        transaction = (
            write_file_transaction(
                transaction_root,
                writes,
                expected=expected,
                claimed_directories=claimed_directories,
            )
            if writes
            else nullcontext()
        )
        try:
            with transaction:
                workspace = load_studio(notebook_path)
        except ConditionalWriteError as error:
            raise WorkspaceMutationError(
                "View creation",
                recovery=error.recovery,
                write_committed=error.committed is not None,
            ) from error
    return ViewSetupResult(
        workspace=workspace,
        notebook=notebook_path,
        config_path=config_path,
        name=selected,
        root=view_root / selected,
        provider=provider_id,
        documents=selected_documents,
        created=created,
        updated=updated,
        dry_run=dry_run,
        launch_requirements=launch_requirements,
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
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")
    saved_notebook = _saved_notebook(notebook_path, inspect_notebook)
    config_snapshot = _studio_snapshot(notebook_path)
    studio = config_snapshot.studio if config_snapshot is not None else None
    config_source = config_snapshot.source if config_snapshot is not None else None
    config_identity = (
        config_snapshot.config_identity if config_snapshot is not None else None
    )
    _require_notebook_config_identity(config_snapshot, saved_notebook)
    selected = name or (studio.default_view if studio is not None else "dashboard")
    validate_view_name(selected)
    if (
        fail_if_exists
        and (canonical_view_root(notebook_path) / selected / "view.toml").is_file()
    ):
        raise ViewExistsError(selected)
    if dry_run:
        return _prepare_view_locked(
            notebook_path,
            name,
            starter=starter,
            inspect_notebook=inspect_notebook,
            dry_run=True,
            fail_if_exists=fail_if_exists,
        )
    default_view = studio.default_view if studio is not None else selected
    view_root = canonical_view_root(notebook_path)
    reject_mutable_symlinks(notebook_path.parent, {view_root})
    _reject_workspace_ignore_shape(view_root)
    view_names = tuple(dict.fromkeys((default_view, selected)))
    _reject_manifestless_view_directories(view_root, view_names)
    missing = tuple(
        view_name
        for view_name in view_names
        if not (view_root / view_name / "view.toml").is_file()
    )
    preplanned: _PreparedStarter | None = None
    prepared_existing: _PreparedExistingView | None = None
    pending_starter: Starter | None = None
    plans: dict[str, StarterPlan] = {}
    if missing:
        pending_starter, provider, provider_starter = _select_starter(starter)
        preplanned = _prepare_starter(
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
        prepared_existing = _prepare_existing_view(current_views[selected])
    if studio is None or studio.uses_notebook_config:
        bindings = (
            starter_bindings(saved_notebook.notebook, studio, plans.values())
            if missing
            else {}
        )
        configured_notebook_source(
            notebook_path,
            default_view,
            _workspace_provider_requirements(view_root, pending_starter),
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
        _workspace_provider_ids(view_root, pending_starter)
    )
    with workspace_catalog_lock(view_root):
        locked_studio = discover_studio_definition(notebook_path)
        if expected_catalog_generation is not None:
            if locked_studio is None:
                raise WorkspaceGenerationConflictError()
            try:
                current_generation = load_studio(notebook_path).catalog_generation
            except WorkspaceInitializationError:
                current_generation = locked_studio.config_generation
            if current_generation != expected_catalog_generation:
                raise WorkspaceGenerationConflictError()
        locked_selected = name or (
            locked_studio.default_view if locked_studio is not None else "dashboard"
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
            return _prepare_view_locked(
                notebook_path,
                name,
                starter=starter,
                inspect_notebook=inspect_notebook,
                dry_run=False,
                preplanned=preplanned,
                prepared_existing=prepared_existing,
                prevalidated_launch_requirements=prevalidated_launch_requirements,
                fail_if_exists=fail_if_exists,
            )
