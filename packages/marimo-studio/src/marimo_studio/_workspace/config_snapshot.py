"""Capture the configuration read set for one workspace mutation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from marimo_studio._filesystem.io import (
    read_file_snapshot_with_identity,
    reject_mutable_symlinks,
)
from marimo_studio._filesystem.secure import FileIdentity
from marimo_studio._workspace.config import studio_definition_from_source
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio.errors import ConfigurationError, WorkspaceGenerationConflictError

_TStudio = TypeVar("_TStudio", bound=StudioDefinition)


@dataclass(frozen=True)
class WorkspaceConfigSnapshot(Generic[_TStudio]):
    """One confirmed Studio configuration source and mutation read set."""

    studio: _TStudio
    source: str
    config_identity: FileIdentity
    notebook_source: str | None
    notebook_identity: FileIdentity | None

    @property
    def expected_identities(self) -> dict[Path, FileIdentity]:
        expected = {self.studio.config_path: self.config_identity}
        if self.notebook_identity is not None:
            expected[self.studio.notebook] = self.notebook_identity
        return expected


def _source_and_identity(path: Path, root: Path) -> tuple[str, FileIdentity]:
    payload, _mode, identity = read_file_snapshot_with_identity(path, root=root)
    try:
        return payload.decode("utf-8"), identity
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"Workspace file is not UTF-8 text: {path}") from error


def _configuration_semantics(studio: StudioDefinition) -> tuple[object, ...]:
    return (
        studio.root,
        studio.config_path,
        studio.config_source,
        studio.notebook,
        studio.view_root,
        studio.default_view,
        studio.default_runtime,
        studio.runtimes,
        studio.preserve_session,
        studio.show_cell_logs,
        tuple(sorted(studio.cells.items())),
    )


def snapshot_workspace_config(
    studio: _TStudio,
    *,
    reload_studio: Callable[[Path], _TStudio],
    include_notebook: bool = False,
    require_catalog_generation: bool = False,
) -> WorkspaceConfigSnapshot[_TStudio]:
    """Read configuration identities and confirm them through a fresh load."""
    paths = {studio.config_path}
    if include_notebook:
        paths.add(studio.notebook)
    reject_mutable_symlinks(studio.root, paths)
    source, config_identity = _source_and_identity(
        studio.config_path,
        studio.root,
    )
    source_studio = studio_definition_from_source(studio.config_path, source)
    notebook_identity: FileIdentity | None = None
    notebook_source: str | None = None
    if include_notebook:
        if studio.notebook == studio.config_path:
            notebook_source = source
            notebook_identity = config_identity
        else:
            notebook_source, notebook_identity = _source_and_identity(
                studio.notebook,
                studio.root,
            )

    current = reload_studio(studio.config_path)
    _confirmed_source, confirmed_config = _source_and_identity(
        studio.config_path,
        studio.root,
    )
    confirmed_notebook: FileIdentity | None = None
    if include_notebook:
        if studio.notebook == studio.config_path:
            confirmed_notebook = confirmed_config
        else:
            _confirmed_notebook_source, confirmed_notebook = _source_and_identity(
                studio.notebook,
                studio.root,
            )
    generation_changed = require_catalog_generation and (
        not isinstance(studio, StudioWorkspace)
        or not isinstance(current, StudioWorkspace)
        or current.catalog_generation != studio.catalog_generation
    )
    if generation_changed:
        raise WorkspaceGenerationConflictError()
    if (
        confirmed_config != config_identity
        or confirmed_notebook != notebook_identity
        or _configuration_semantics(current) != _configuration_semantics(source_studio)
    ):
        raise ConfigurationError(
            "Studio configuration changed while its snapshot was captured. "
            "Run the operation again."
        )
    return WorkspaceConfigSnapshot(
        current,
        source,
        config_identity,
        notebook_source,
        notebook_identity,
    )
