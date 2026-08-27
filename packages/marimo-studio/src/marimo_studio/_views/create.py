"""Create notebook-local Studio view files."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.inputs import (
    ProjectInputState,
    project_input_state,
    project_revision_snapshot,
)
from marimo_studio._filesystem.io import read_text, reject_mutable_symlinks
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._views.catalog import resolve_starter
from marimo_studio._views.inspection import (
    inspect_view_project_sync,
)
from marimo_studio._views.records import Starter, ViewSetupResult
from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    discover_views,
    load_studio,
    validate_view_name,
)
from marimo_studio._workspace.metadata import configured_notebook_source
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import ConfigurationError, ViewExistsError
from marimo_studio.view_providers import (
    ProjectInspection,
    ProviderStarter,
    StarterContext,
    ViewProject,
    ViewProvider,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.package_policy import DEFAULT_STARTER_ID

SetupPlan = tuple[
    Starter,
    ViewProvider,
    ProviderStarter,
    dict[str, Mapping[PurePosixPath, bytes]],
]
_WORKSPACE_IGNORE_RULES = ("/.locks/", "*/.artifacts/")


@dataclass(frozen=True)
class _PreparedExistingView:
    project: ViewProject
    inspection: ProjectInspection
    input_state: ProjectInputState


def _prepare_existing_view(project: ViewProject) -> _PreparedExistingView:
    inspection = inspect_view_project_sync(project)
    provider = provider_registry().get(project.provider)
    snapshot = project_revision_snapshot(
        project,
        inspection,
        provider.provenance(inspection),
    )
    return _PreparedExistingView(project, inspection, snapshot.state)


def _workspace_ignore_source(path: Path) -> str:
    source = read_text(path) if path.is_file() else ""
    present = {line.strip() for line in source.splitlines()}
    missing = tuple(rule for rule in _WORKSPACE_IGNORE_RULES if rule not in present)
    if not missing:
        return source
    prefix = source if not source or source.endswith("\n") else f"{source}\n"
    return prefix + "".join(f"{rule}\n" for rule in missing)


def _select_starter(
    value: str | Starter | None,
) -> tuple[Starter, ViewProvider, ProviderStarter]:
    identity = value.id if isinstance(value, Starter) else value or DEFAULT_STARTER_ID
    starter, provider, template = resolve_starter(identity)
    if not starter.availability.available:
        reason = starter.availability.reason or "The provider is unavailable."
        action = starter.availability.action
        detail = f" {action}" if action is not None else ""
        raise ConfigurationError(
            f"Starter {identity!r} is unavailable: {reason}{detail}"
        )
    return starter, provider, template


def _workspace_provider_requirements(
    view_root: Path,
    starter: Starter | None,
) -> tuple[str, ...]:
    provider_ids = {project.provider for project in discover_views(view_root).values()}
    if starter is not None:
        provider_ids.add(starter.provider)
    registry = provider_registry()
    return tuple(
        registry.get(provider_id).requirement for provider_id in sorted(provider_ids)
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


def _ensure_view_locked(
    notebook: str | Path,
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    preplanned: SetupPlan | None = None,
    prepared_existing: _PreparedExistingView | None = None,
) -> ViewSetupResult:
    """Configure a notebook when needed and create a named view."""
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")
    studio = discover_studio_definition(notebook_path)
    selected = name or (studio.default_view if studio is not None else "dashboard")
    validate_view_name(selected)
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
    plans: dict[str, Mapping[PurePosixPath, bytes]] = {}
    template: ProviderStarter | None
    if new_views:
        if preplanned is None:
            selected_starter, provider, template = _select_starter(starter)
        else:
            selected_starter, provider, template, plans = preplanned
    else:
        selected_starter = None
        provider = None
        template = None
    provider_requirements: tuple[str, ...] = ()
    if studio is None or studio.uses_notebook_config:
        provider_requirements = _workspace_provider_requirements(
            view_root,
            selected_starter,
        )

    writes: dict[Path, str | bytes] = {}
    if studio is None or studio.uses_notebook_config:
        configured = configured_notebook_source(
            notebook_path,
            default_view,
            provider_requirements,
            {},
        )
        if configured != read_text(notebook_path):
            writes[notebook_path] = configured
        config_path = notebook_path
        transaction_root = notebook_path.parent
    else:
        config_path = studio.config_path
        transaction_root = studio.root

    workspace_ignore = view_root / ".gitignore"
    ignore_source = _workspace_ignore_source(workspace_ignore)
    if not workspace_ignore.is_file() or ignore_source != read_text(workspace_ignore):
        writes[workspace_ignore] = ignore_source

    planned_documents: dict[str, tuple[Path, ...]] = {}
    for view_name in new_views:
        assert selected_starter is not None
        assert provider is not None
        assert template is not None
        plan = plans.get(view_name)
        if plan is None:
            if not dry_run:
                raise ConfigurationError(
                    "The view catalog changed while starter files were prepared. "
                    "Run the operation again."
                )
            plan = provider.create(
                template,
                StarterContext(view_name, notebook_path.stem),
            )
        project_root = view_root / view_name
        planned_documents[view_name] = (
            project_root / "view.toml",
            *(project_root / relative for relative in selected_starter.documents),
        )
        writes[project_root / "view.toml"] = encode_view_manifest(
            selected_starter.provider
        )
        for relative, payload in plan.items():
            path = project_root / relative
            if not path.exists():
                writes[path] = payload

    created = tuple(sorted(path for path in writes if not path.exists()))
    updated = tuple(sorted(path for path in writes if path.exists()))
    workspace = None
    if not dry_run:
        transaction = (
            write_file_transaction(transaction_root, writes)
            if writes
            else nullcontext()
        )
        with transaction:
            workspace = load_studio(notebook_path)
    if selected_starter is not None and selected in planned_documents:
        selected_documents = planned_documents.get(selected, ())
        provider_id = selected_starter.provider
    else:
        current = workspace or load_studio(notebook_path)
        project = current.views[selected]
        if prepared_existing is not None:
            if (
                project != prepared_existing.project
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
        elif preplanned is not None and selected in preplanned[3]:
            planned_starter = preplanned[0]
            if project.provider != planned_starter.provider:
                raise ConfigurationError(
                    "The selected view changed while starter files were prepared. "
                    "Run the operation again."
                )
            selected_documents = (
                project.manifest,
                *(project.root / path for path in planned_starter.documents),
            )
        elif dry_run:
            inspection = inspect_view_project_sync(project)
            selected_documents = (
                project.manifest,
                *(project.root / item.path for item in inspection.editor_documents),
            )
        else:
            raise ConfigurationError(
                "The selected view changed while its provider documents were "
                "inspected. Run the operation again."
            )
        provider_id = project.provider
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
    )


def ensure_view(
    notebook: str | Path,
    name: str | None = None,
    *,
    starter: str | Starter | None = None,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    fail_if_exists: bool = False,
) -> ViewSetupResult:
    """Configure a notebook when needed and create a named view."""
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")
    inspect_notebook(notebook_path)
    studio = discover_studio_definition(notebook_path)
    selected = name or (studio.default_view if studio is not None else "dashboard")
    validate_view_name(selected)
    if (
        fail_if_exists
        and (canonical_view_root(notebook_path) / selected / "view.toml").is_file()
    ):
        raise ViewExistsError(selected)
    if dry_run:
        return _ensure_view_locked(
            notebook_path,
            name,
            starter=starter,
            inspect_notebook=inspect_notebook,
            dry_run=True,
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
    preplanned: SetupPlan | None = None
    prepared_existing: _PreparedExistingView | None = None
    pending_starter: Starter | None = None
    if missing:
        pending_starter, provider, template = _select_starter(starter)
        plans = {
            view_name: provider.create(
                template,
                StarterContext(view_name, notebook_path.stem),
            )
            for view_name in missing
        }
        preplanned = (pending_starter, provider, template, plans)
    current_views = discover_views(view_root)
    if selected in current_views and selected not in missing:
        prepared_existing = _prepare_existing_view(current_views[selected])
    if studio is None or studio.uses_notebook_config:
        configured_notebook_source(
            notebook_path,
            default_view,
            _workspace_provider_requirements(view_root, pending_starter),
            {},
        )
    with workspace_catalog_lock(view_root):
        locked_studio = discover_studio_definition(notebook_path)
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
            return _ensure_view_locked(
                notebook_path,
                name,
                starter=starter,
                inspect_notebook=inspect_notebook,
                dry_run=False,
                preplanned=preplanned,
                prepared_existing=prepared_existing,
            )
