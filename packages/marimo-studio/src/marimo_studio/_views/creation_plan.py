"""Plan atomic view creation from validated workspace state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from marimo_studio._artifacts.inputs import (
    ProjectInputState,
    project_input_state,
    project_revision_snapshot,
)
from marimo_studio._filesystem._secure_types import FileIdentity
from marimo_studio._filesystem.io import read_file_snapshot_with_identity
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.records import CellRef, NotebookSpec
from marimo_studio._notebook.source_snapshot import inspect_notebook_source
from marimo_studio._views.catalog import resolve_starter
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._views.records import Starter
from marimo_studio._views.starter_context import starter_bindings, starter_context
from marimo_studio._workspace.bindings import cell_bindings_source
from marimo_studio._workspace.config import discover_views
from marimo_studio._workspace.config_snapshot import WorkspaceConfigSnapshot
from marimo_studio._workspace.metadata import configured_notebook_source
from marimo_studio._workspace.models import StudioDefinition
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio._workspace.view_owners import view_owner_transition
from marimo_studio.errors import ConfigurationError
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
class PreparedExistingView:
    project: ViewProject
    inspection: ProjectInspection
    input_state: ProjectInputState


@dataclass(frozen=True)
class SavedNotebook:
    notebook: NotebookSpec
    source: str
    identity: FileIdentity


@dataclass(frozen=True)
class PreparedStarter:
    starter: Starter
    provider: ViewProvider
    provider_starter: ProviderStarter
    observed_studio: StudioDefinition | None
    observed_config_identity: FileIdentity | None
    observed_notebook: NotebookSpec
    planned_notebook: NotebookSpec
    planned_source: str
    plans: dict[str, StarterPlan]


@dataclass(frozen=True)
class ValidatedViewCreation:
    notebook_path: Path
    saved_notebook: SavedNotebook
    config_snapshot: WorkspaceConfigSnapshot[StudioDefinition] | None
    studio: StudioDefinition | None
    config_identity: FileIdentity | None
    selected: str
    default_view: str
    view_root: Path
    new_views: tuple[str, ...]


@dataclass(frozen=True)
class ViewCreationPlan:
    transaction_root: Path
    writes: Mapping[Path, str | bytes]
    expected_identities: Mapping[Path, FileIdentity | None]
    claimed_directories: Mapping[Path, tuple[PurePosixPath, ...]]
    notebook: Path
    config_path: Path
    name: str
    root: Path
    provider: str
    documents: tuple[Path, ...]
    created: tuple[Path, ...]
    updated: tuple[Path, ...]
    launch_requirements: tuple[str, ...]


@dataclass(frozen=True)
class _ConfigurationTransition:
    transaction_root: Path
    config_path: Path
    write: tuple[Path, str] | None
    expected_identities: dict[Path, FileIdentity | None]


@dataclass(frozen=True)
class _NewProjectWrites:
    writes: dict[Path, str | bytes]
    manifests: dict[Path, str]
    expected_identities: dict[Path, FileIdentity | None]
    claimed_directories: dict[Path, tuple[PurePosixPath, ...]]
    documents: dict[str, tuple[Path, ...]]


@dataclass(frozen=True)
class _SelectedView:
    provider: str
    documents: tuple[Path, ...]


def prepare_existing_view(project: ViewProject) -> PreparedExistingView:
    inspection = inspect_view_project_sync(project)
    provider = provider_registry().get(project.provider)
    snapshot = project_revision_snapshot(
        project,
        inspection,
        provider.provenance(inspection),
    )
    return PreparedExistingView(project, inspection, snapshot.state)


def select_starter(
    value: str | Starter | None,
) -> tuple[Starter, ViewProvider, ProviderStarter]:
    identity = value.id if isinstance(value, Starter) else value or DEFAULT_STARTER_ID
    starter, provider, provider_starter = resolve_starter(identity)
    if starter.availability.available:
        return starter, provider, provider_starter
    reason = starter.availability.reason or "The provider is unavailable."
    action = starter.availability.action
    detail = f" {action}" if action is not None else ""
    raise ConfigurationError(f"Starter {identity!r} is unavailable: {reason}{detail}")


def workspace_provider_ids(
    view_root: Path,
    starter: Starter | None,
) -> tuple[str, ...]:
    provider_ids = {project.provider for project in discover_views(view_root).values()}
    if starter is not None:
        provider_ids.add(starter.provider)
    return tuple(sorted(provider_ids))


def workspace_provider_requirements(
    view_root: Path,
    starter: Starter | None,
) -> tuple[str, ...]:
    registry = provider_registry()
    return tuple(
        registry.get(provider_id).requirement
        for provider_id in workspace_provider_ids(view_root, starter)
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


def prepare_starter(
    notebook_path: Path,
    saved: SavedNotebook,
    studio: StudioDefinition | None,
    config_identity: FileIdentity | None,
    view_root: Path,
    default_view: str,
    view_names: tuple[str, ...],
    starter: Starter,
    provider: ViewProvider,
    provider_starter: ProviderStarter,
    inspect_notebook: NotebookInspector,
) -> PreparedStarter:
    initial = _provider_plans(
        provider,
        provider_starter,
        saved.notebook,
        studio,
        view_names,
    )
    if studio is not None and not studio.uses_notebook_config:
        return PreparedStarter(
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
        workspace_provider_requirements(view_root, starter),
        bindings,
        source=saved.source,
    )
    if configured == saved.source:
        return PreparedStarter(
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
        workspace_provider_requirements(view_root, starter),
        final_bindings,
        source=saved.source,
    )
    if final_source != configured:
        raise ConfigurationError(
            "Starter configuration changed after provider planning. "
            "Run the operation again."
        )
    return PreparedStarter(
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


def _revalidate_prepared_starter(
    validated: ValidatedViewCreation,
    prepared: PreparedStarter,
    inspect_notebook: NotebookInspector,
) -> PreparedStarter:
    saved = validated.saved_notebook
    current_revision = saved.notebook.revision
    if current_revision not in {
        prepared.observed_notebook.revision,
        prepared.planned_notebook.revision,
    }:
        raise ConfigurationError(
            "The notebook changed while starter files were prepared. "
            "Run the operation again."
        )
    if (
        validated.studio == prepared.observed_studio
        and validated.config_identity == prepared.observed_config_identity
    ):
        return prepared
    expected_notebook_transition = (
        (
            prepared.observed_studio is None
            or prepared.observed_studio.uses_notebook_config
        )
        and validated.studio is not None
        and validated.studio.uses_notebook_config
        and current_revision == prepared.planned_notebook.revision
        and saved.source == prepared.planned_source
    )
    if expected_notebook_transition:
        return prepared
    if prepared.observed_studio is None and (
        validated.studio is not None and validated.studio.uses_notebook_config
    ):
        return prepare_starter(
            validated.notebook_path,
            saved,
            validated.studio,
            validated.config_identity,
            validated.view_root,
            validated.default_view,
            validated.new_views,
            prepared.starter,
            prepared.provider,
            prepared.provider_starter,
            inspect_notebook,
        )
    raise ConfigurationError(
        "Studio configuration changed while starter files were prepared. "
        "Run the operation again."
    )


def _prepared_starter_for_plan(
    validated: ValidatedViewCreation,
    *,
    starter: str | Starter | None,
    inspect_notebook: NotebookInspector,
    dry_run: bool,
    preplanned: PreparedStarter | None,
) -> PreparedStarter | None:
    if not validated.new_views:
        return None
    if preplanned is not None:
        return _revalidate_prepared_starter(validated, preplanned, inspect_notebook)
    if not dry_run:
        raise ConfigurationError(
            "The view catalog changed before starter planning completed. "
            "Run the operation again."
        )
    selected, provider, provider_starter = select_starter(starter)
    return prepare_starter(
        validated.notebook_path,
        validated.saved_notebook,
        validated.studio,
        validated.config_identity,
        validated.view_root,
        validated.default_view,
        validated.new_views,
        selected,
        provider,
        provider_starter,
        inspect_notebook,
    )


def _configuration_transition(
    validated: ValidatedViewCreation,
    prepared: PreparedStarter | None,
    provider_requirements: tuple[str, ...],
    bindings: Mapping[str, CellRef],
    inspect_notebook: NotebookInspector,
) -> _ConfigurationTransition:
    studio = validated.studio
    saved = validated.saved_notebook
    notebook_path = validated.notebook_path
    expected: dict[Path, FileIdentity | None] = {}
    if studio is None or studio.uses_notebook_config:
        expected[notebook_path] = saved.identity
        configured = configured_notebook_source(
            notebook_path,
            validated.default_view,
            provider_requirements,
            bindings,
            source=saved.source,
        )
        if prepared is not None:
            prospective = (
                saved.notebook
                if configured == saved.source
                else inspect_notebook_source(
                    notebook_path,
                    configured,
                    inspect_notebook,
                    include_code=True,
                )
            )
            if prospective.revision != prepared.planned_notebook.revision:
                raise ConfigurationError(
                    "Notebook configuration changed while starter files were "
                    "prepared. Run the operation again."
                )
        write = (notebook_path, configured) if configured != saved.source else None
        return _ConfigurationTransition(
            notebook_path.parent,
            notebook_path,
            write,
            expected,
        )

    if prepared is not None:
        expected[notebook_path] = saved.identity
    snapshot = validated.config_snapshot
    assert snapshot is not None
    expected.update(snapshot.expected_identities)
    configured = cell_bindings_source(studio, bindings, source=snapshot.source)
    write = (studio.config_path, configured) if configured != snapshot.source else None
    return _ConfigurationTransition(
        studio.root,
        studio.config_path,
        write,
        expected,
    )


def _new_project_writes(
    validated: ValidatedViewCreation,
    prepared: PreparedStarter | None,
) -> _NewProjectWrites:
    writes: dict[Path, str | bytes] = {}
    manifests: dict[Path, str] = {}
    expected: dict[Path, FileIdentity | None] = {}
    claimed: dict[Path, tuple[PurePosixPath, ...]] = {}
    documents: dict[str, tuple[Path, ...]] = {}
    if prepared is None:
        if validated.new_views:
            raise ConfigurationError(
                "The view catalog changed while starter files were prepared. "
                "Run the operation again."
            )
        return _NewProjectWrites(writes, manifests, expected, claimed, documents)

    for view_name in validated.new_views:
        plan = prepared.plans.get(view_name)
        if plan is None:
            raise ConfigurationError(
                "The view catalog changed while starter files were prepared. "
                "Run the operation again."
            )
        project_root = validated.view_root / view_name
        manifest = project_root / "view.toml"
        claimed[project_root] = (PurePosixPath("view.toml"), *plan.files.keys())
        documents[view_name] = (
            manifest,
            *(project_root / path for path in prepared.starter.documents),
        )
        expected[manifest] = None
        for relative, payload in plan.files.items():
            path = project_root / relative
            expected[path] = None
            writes[path] = payload
        manifests[manifest] = encode_view_manifest(prepared.starter.provider)
        owner_path, owner_source, owner_identity = view_owner_transition(
            validated.view_root,
            view_name,
            present=True,
        )
        expected[owner_path] = owner_identity
        writes[owner_path] = owner_source
    return _NewProjectWrites(writes, manifests, expected, claimed, documents)


def _selected_view(
    validated: ValidatedViewCreation,
    prepared: PreparedStarter | None,
    project_writes: _NewProjectWrites,
    *,
    preplanned: PreparedStarter | None,
    prepared_existing: PreparedExistingView | None,
    dry_run: bool,
) -> _SelectedView:
    selected = validated.selected
    if prepared is not None and selected in project_writes.documents:
        return _SelectedView(
            prepared.starter.provider,
            project_writes.documents[selected],
        )
    if prepared_existing is not None:
        project = discover_views(validated.view_root).get(selected)
        if (
            project == prepared_existing.project
            and project is not None
            and project_input_state(project, prepared_existing.inspection)
            == prepared_existing.input_state
        ):
            return _SelectedView(
                project.provider,
                (
                    project.manifest,
                    *(
                        project.root / item.path
                        for item in prepared_existing.inspection.editor_documents
                    ),
                ),
            )
        raise ConfigurationError(
            "The selected view changed while its provider documents were "
            "inspected. Run the operation again."
        )
    if preplanned is not None and selected in preplanned.plans:
        project = discover_views(validated.view_root).get(selected)
        if project is not None and project.provider == preplanned.starter.provider:
            return _SelectedView(
                project.provider,
                (
                    project.manifest,
                    *(project.root / path for path in preplanned.starter.documents),
                ),
            )
        raise ConfigurationError(
            "The selected view changed while starter files were prepared. "
            "Run the operation again."
        )
    if dry_run:
        project = discover_views(validated.view_root).get(selected)
        if project is not None:
            inspection = inspect_view_project_sync(project)
            return _SelectedView(
                project.provider,
                (
                    project.manifest,
                    *(project.root / item.path for item in inspection.editor_documents),
                ),
            )
        raise ConfigurationError(
            f"View {selected!r} changed while its source plan was prepared. "
            "Run the operation again."
        )
    raise ConfigurationError(
        "The selected view changed while its provider documents were inspected. "
        "Run the operation again."
    )


def _workspace_ignore_source(source: str) -> str:
    present = {line.strip() for line in source.splitlines()}
    missing = tuple(rule for rule in _WORKSPACE_IGNORE_RULES if rule not in present)
    if not missing:
        return source
    prefix = source if not source or source.endswith("\n") else f"{source}\n"
    return prefix + "".join(f"{rule}\n" for rule in missing)


def _optional_text_snapshot(path: Path) -> tuple[str, FileIdentity | None]:
    try:
        payload, _mode, identity = read_file_snapshot_with_identity(path)
    except FileNotFoundError:
        return "", None
    try:
        return payload.decode("utf-8"), identity
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"Workspace file is not UTF-8 text: {path}") from error


def build_view_creation_plan(
    validated: ValidatedViewCreation,
    *,
    starter: str | Starter | None = None,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    preplanned: PreparedStarter | None = None,
    prepared_existing: PreparedExistingView | None = None,
    prevalidated_launch_requirements: tuple[str, ...] | None = None,
) -> ViewCreationPlan:
    prepared = _prepared_starter_for_plan(
        validated,
        starter=starter,
        inspect_notebook=inspect_notebook,
        dry_run=dry_run,
        preplanned=preplanned,
    )
    selected_starter = prepared.starter if prepared is not None else None
    provider_ids = workspace_provider_ids(validated.view_root, selected_starter)
    launch_requirements = resolve_launch_requirements(provider_ids)
    if (
        prevalidated_launch_requirements is not None
        and launch_requirements != prevalidated_launch_requirements
    ):
        raise ConfigurationError(
            "View provider requirements changed before creation. "
            "Run the operation again."
        )

    plans = prepared.plans if prepared is not None else {}
    bindings = (
        starter_bindings(
            prepared.planned_notebook,
            validated.studio,
            (plans[name] for name in validated.new_views),
        )
        if prepared is not None
        else {}
    )
    requirements = (
        workspace_provider_requirements(validated.view_root, selected_starter)
        if validated.studio is None or validated.studio.uses_notebook_config
        else ()
    )
    transition = _configuration_transition(
        validated,
        prepared,
        requirements,
        bindings,
        inspect_notebook,
    )
    projects = _new_project_writes(validated, prepared)

    writes: dict[Path, str | bytes] = {}
    expected = dict(transition.expected_identities)
    workspace_ignore = validated.view_root / ".gitignore"
    current_ignore, ignore_identity = _optional_text_snapshot(workspace_ignore)
    expected[workspace_ignore] = ignore_identity
    ignore_source = _workspace_ignore_source(current_ignore)
    if ignore_source != current_ignore:
        writes[workspace_ignore] = ignore_source
    writes.update(projects.writes)
    expected.update(projects.expected_identities)
    if validated.studio is None:
        writes.update(projects.manifests)
        if transition.write is not None:
            writes[transition.write[0]] = transition.write[1]
    else:
        if transition.write is not None:
            writes[transition.write[0]] = transition.write[1]
        writes.update(projects.manifests)

    selected = _selected_view(
        validated,
        prepared,
        projects,
        preplanned=preplanned,
        prepared_existing=prepared_existing,
        dry_run=dry_run,
    )
    return ViewCreationPlan(
        transaction_root=transition.transaction_root,
        writes=MappingProxyType(writes),
        expected_identities=MappingProxyType(expected),
        claimed_directories=MappingProxyType(projects.claimed_directories),
        notebook=validated.notebook_path,
        config_path=transition.config_path,
        name=validated.selected,
        root=validated.view_root / validated.selected,
        provider=selected.provider,
        documents=selected.documents,
        created=tuple(sorted(path for path in writes if not path.exists())),
        updated=tuple(sorted(path for path in writes if path.exists())),
        launch_requirements=launch_requirements,
    )
