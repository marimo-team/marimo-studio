"""Capture notebook source and published artifacts for presentation.

Capture hashes the saved notebook, Studio configuration, and cell bindings,
then pairs each selected view with a leased immutable artifact and an explicit
presentation revision. Consumers compare those revisions when later evidence
must still belong to the source they observed.

Artifact leases transfer explicitly to the presentation owner and remain open
for as long as that revision may be requested. Capture can build current source
or retain an existing publication, which gives presentation and validation
services a precise last-working fallback when a new build fails.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType

from marimo_studio._artifacts.inputs import project_revision
from marimo_studio._artifacts.records import ViewArtifact
from marimo_studio._artifacts.retention import ArtifactLease, lease_published_artifact
from marimo_studio._filesystem.io import read_bytes
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._views.build import publish_view
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    ViewNotFoundError,
)
from marimo_studio.view_providers import BuildProfile, ProjectInspection
from marimo_studio.view_providers._host import provider_registry


def _close_leases(
    leases: tuple[ArtifactLease, ...],
    failure: BaseException | None = None,
) -> None:
    for lease in leases:
        try:
            lease.close()
        except BaseException as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise failure


def _configuration_identity(studio: StudioWorkspace) -> tuple[object, ...]:
    return (
        str(studio.config_path),
        studio.config_source,
        str(studio.notebook),
        str(studio.view_root),
        studio.default_view,
        studio.default_runtime,
        studio.runtimes,
        studio.preserve_session,
        studio.show_cell_logs,
        tuple(
            (
                name,
                str(project.root),
                project.provider,
            )
            for name, project in studio.views.items()
        ),
        tuple(
            (alias, str(reference)) for alias, reference in sorted(studio.cells.items())
        ),
    )


def _selected_views(
    studio: StudioWorkspace,
    view_names: tuple[str, ...] | None,
) -> tuple[str, ...]:
    selected = (
        tuple(studio.views) if view_names is None else tuple(dict.fromkeys(view_names))
    )
    unknown = set(selected).difference(studio.views)
    if unknown:
        raise ViewNotFoundError(sorted(unknown)[0], available=tuple(studio.views))
    return selected


def _presentation_source(studio: StudioWorkspace) -> tuple[str, tuple[object, ...]]:
    paths = tuple(dict.fromkeys((studio.config_path, studio.notebook)))
    contents = {path: read_bytes(path, root=path.parent) for path in paths}
    try:
        notebook_source = contents[studio.notebook].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError(
            f"Could not decode {studio.notebook} as UTF-8: {error}"
        ) from error
    source_identity = tuple(
        (str(path), hashlib.sha256(contents[path]).hexdigest()) for path in paths
    )
    return notebook_source, (_configuration_identity(studio), source_identity)


def capture_source_revisions(
    studio: StudioWorkspace,
    view_names: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Hash current notebook, configuration, and declared provider inputs."""
    selected = _selected_views(studio, view_names)
    _notebook_source, base_identity = _presentation_source(studio)
    revisions: dict[str, str] = {}
    for name in selected:
        project = studio.views[name]
        provider = provider_registry().get(project.provider)
        inspection = inspect_view_project_sync(project)
        input_id = project_revision(
            project,
            inspection,
            provider.provenance(inspection),
        )
        identity = (name, base_identity, input_id)
        revisions[name] = hashlib.sha256(repr(identity).encode()).hexdigest()
    return revisions


@dataclass
class PresentationSourceSnapshot:
    """Leased artifacts and notebook source captured for presentation."""

    leases: dict[str, ArtifactLease]
    notebook_source: str
    base_identity: tuple[object, ...]

    @property
    def source_revision(self) -> str:
        """Identify the saved notebook and Studio configuration snapshot."""
        return hashlib.sha256(repr(self.base_identity).encode()).hexdigest()

    def revision(self, view_name: str) -> str:
        artifact = self.leases[view_name].artifact
        identity = (
            view_name,
            self.base_identity,
            artifact.profile,
            artifact.artifact_revision,
        )
        return hashlib.sha256(repr(identity).encode()).hexdigest()

    @property
    def revisions(self) -> dict[str, str]:
        return {name: self.revision(name) for name in self.leases}

    @property
    def artifacts(self) -> dict[str, ViewArtifact]:
        return {name: lease.artifact for name, lease in self.leases.items()}

    def take_lease(self, view_name: str) -> ArtifactLease:
        """Transfer one view artifact to a longer-lived presentation owner."""
        return self.leases.pop(view_name)

    def close(self) -> None:
        leases = tuple(self.leases.values())
        self.leases.clear()
        _close_leases(leases)

    def __enter__(self) -> PresentationSourceSnapshot:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        except BaseException:
            if _exception is None:
                raise


@dataclass(frozen=True)
class PreparedViewProject:
    """One watcher-generation inspection and its complete input identity."""

    inspection: ProjectInspection
    input_id: str


def capture_presentations(
    studio: StudioWorkspace,
    view_names: tuple[str, ...] | None = None,
    *,
    profile: BuildProfile = "development",
    prepared: Mapping[str, PreparedViewProject] | None = None,
) -> PresentationSourceSnapshot:
    """Publish selected artifacts and capture shared notebook source."""
    selected = _selected_views(studio, view_names)
    notebook_source, base_identity = _presentation_source(studio)
    leases: dict[str, ArtifactLease] = {}
    try:
        for name in selected:
            project = studio.views[name]
            try:
                snapshot = prepared.get(name) if prepared is not None else None
                leases[name] = (
                    publish_view(project, profile)
                    if snapshot is None
                    else publish_view(
                        project,
                        profile,
                        inspection=snapshot.inspection,
                        input_id=snapshot.input_id,
                    )
                )
            except MarimoStudioError as error:
                raise_process_cleanup(error)
                retained = lease_published_artifact(project, profile)
                if retained is None:
                    raise
                leases[name] = retained
        return PresentationSourceSnapshot(
            leases=leases,
            notebook_source=notebook_source,
            base_identity=base_identity,
        )
    except BaseException as error:
        retained = tuple(leases.values())
        leases.clear()
        _close_leases(retained, error)
        raise error


def capture_published_presentations(
    studio: StudioWorkspace,
    view_names: tuple[str, ...] | None = None,
    *,
    profile: BuildProfile = "development",
) -> PresentationSourceSnapshot | None:
    """Capture existing publications without running providers."""
    selected = _selected_views(studio, view_names)
    notebook_source, base_identity = _presentation_source(studio)
    leases: dict[str, ArtifactLease] = {}
    try:
        for name in selected:
            lease = lease_published_artifact(studio.views[name], profile)
            if lease is None:
                retained = tuple(leases.values())
                leases.clear()
                _close_leases(retained)
                return None
            leases[name] = lease
        return PresentationSourceSnapshot(
            leases=leases,
            notebook_source=notebook_source,
            base_identity=base_identity,
        )
    except BaseException as error:
        retained = tuple(leases.values())
        leases.clear()
        _close_leases(retained, error)
        raise error
