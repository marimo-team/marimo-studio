"""Track authored source changes through one provider input scope."""

from __future__ import annotations

import hashlib
import os
import stat
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from marimo_studio._artifacts.inputs import project_revision
from marimo_studio._artifacts.limits import PROJECT_INPUT_BUDGET
from marimo_studio._artifacts.paths import artifact_root, digest_secure_file
from marimo_studio._filesystem.tree import bounded_tree_entries
from marimo_studio._prepared.state_space import state_space_path
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._server.development.ports import ProjectWatchPlan
from marimo_studio._views.inspection import inspection_request
from marimo_studio._views.publication_hold import (
    publication_hold_path,
    read_publication_hold,
)
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.metadata import notebook_config
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.view_providers import ProjectInspection, ViewProject
from marimo_studio.view_providers._host import provider_registry

_WatchKey = tuple[Literal["root", "view"], Path]
_FileStamp = str | tuple[int, int, int, int]
_TreeStamp = _FileStamp | Literal["directory", "missing", "symlink"]
_StructuralStamp = tuple[tuple[str, _FileStamp | Literal["symlink"]], ...]
_StatStamp = tuple[int, int, int, int, int] | Literal["missing"]


@dataclass(frozen=True)
class SourceChange:
    kind: Literal["project", "resync", "views"]
    files: tuple[dict[str, object], ...]
    error: str | None = None


class SourceChangeProducer:
    """Return changes after one provider inspection and cheap tree scans."""

    def __init__(self, studio: StudioWorkspace, view_name: str | None) -> None:
        self._studio = studio
        self._view_name = view_name
        self._config_stamp = _config_stamp(studio)
        self._notebook_stamp = _path_stamp(studio.notebook)
        self._view_catalog = _view_catalog(studio)
        self._project: ViewProject | None = None
        self._inspection: ProjectInspection | None = None
        self._input_id: str | None = None
        self._inspection_error: Exception | None = None
        self._manifest_stamp: _FileStamp = "missing"
        self._state_space_stamp: _FileStamp = "missing"
        self._publication_hold_stamp: tuple[str, str] | None = None
        self._scope_files: tuple[Path, ...] = ()
        self._roots: tuple[Path, ...] = ()
        self._excluded_roots: tuple[Path, ...] = ()
        self._tree: dict[_WatchKey, _TreeStamp] = {}
        self._catalog_stamps: dict[Path, _StatStamp] = {}
        self._pending: deque[SourceChange] = deque()
        self._workspace_invalid = False
        self._invalid_project_change = False
        self._select_project()

    @property
    def studio(self) -> StudioWorkspace:
        """Return the latest successfully loaded workspace."""
        return self._studio

    @property
    def watch_plan(self) -> ProjectWatchPlan:
        """Return provider documents and bounded build-input directories."""
        files = {
            self._studio.notebook,
            self._studio.config_path,
            self._studio.view_root,
            *(
                self._studio.view_root / name / "view.toml"
                for name, _stamp in self._view_catalog
            ),
        }
        files.update(self._scope_files)
        if self._project is not None:
            files.add(self._project.manifest)
            files.add(state_space_path(self._project.root))
            files.add(publication_hold_path(self._project.root))
        return ProjectWatchPlan(
            files=tuple(sorted((path.absolute() for path in files), key=str)),
            roots=tuple(sorted((path.absolute() for path in self._roots), key=str)),
            excluded=tuple(
                sorted(
                    (path.absolute() for path in self._excluded_roots),
                    key=str,
                )
            ),
        )

    def catalog_current(self) -> bool:
        """Check known inputs without walking or reinspecting the project."""
        project = self._project
        return (
            project is not None
            and _optional_stamp(project.manifest) == self._manifest_stamp
            and _optional_stamp(state_space_path(project.root))
            == self._state_space_stamp
            and _publication_hold_stamp(project) == self._publication_hold_stamp
            and bool(self._catalog_stamps)
            and all(
                _stat_stamp(path) == stamp
                for path, stamp in self._catalog_stamps.items()
            )
        )

    def catalog(self) -> tuple[ViewProject, ProjectInspection, str]:
        """Return the project and inspection captured by the latest scan."""
        if self._project is None:
            raise ConfigurationError("The selected Studio view is unavailable")
        if self._inspection is None:
            message = "Provider inspection is unavailable"
            if self._inspection_error is not None:
                message = f"{message}: {self._inspection_error}"
            raise ConfigurationError(message)
        if self._input_id is None:
            raise ConfigurationError("Provider project identity is unavailable")
        return self._project, self._inspection, self._input_id

    def poll(self) -> SourceChange | None:
        if self._pending:
            return self._pending.popleft()
        if self._workspace_invalid:
            if not self._reload_workspace(rebind_selected=True):
                return None
            project_change = self._invalid_project_change
            self._workspace_invalid = False
            self._invalid_project_change = False
            if project_change:
                self._pending.append(SourceChange(kind="project", files=()))
            return SourceChange(kind="views", files=())
        notebook_stamp = _path_stamp(self._studio.notebook)
        notebook_change = notebook_stamp != self._notebook_stamp
        config_stamp = (
            _config_stamp(self._studio)
            if notebook_change or not self._studio.uses_notebook_config
            else self._config_stamp
        )
        view_catalog = _view_catalog(self._studio)
        selected_manifest_change = _selected_manifest_transition(
            self._view_catalog,
            view_catalog,
            self._view_name,
        )
        config_change = config_stamp != self._config_stamp
        project_change = config_change or selected_manifest_change
        structural_change = config_change or view_catalog != self._view_catalog

        if structural_change:
            reloaded = self._reload_workspace(
                rebind_selected=selected_manifest_change,
            )
            if not reloaded:
                self._workspace_invalid = True
                self._invalid_project_change = project_change
                if project_change:
                    self._pending.append(SourceChange(kind="project", files=()))
                return SourceChange(kind="views", files=())
            if project_change:
                self._pending.append(SourceChange(kind="project", files=()))
            return SourceChange(kind="views", files=())

        self._config_stamp = config_stamp
        self._notebook_stamp = notebook_stamp
        self._view_catalog = view_catalog

        current = _tree_stamps(
            (*self._scope_files, *self._roots),
            self._excluded_roots,
        )
        changed = _changed_keys(self._tree, current)
        state_space_stamp = (
            _optional_stamp(state_space_path(self._project.root))
            if self._project is not None
            else "missing"
        )
        state_space_change = state_space_stamp != self._state_space_stamp
        self._state_space_stamp = state_space_stamp
        publication_hold_stamp = (
            _publication_hold_stamp(self._project)
            if self._project is not None
            else None
        )
        publication_hold_change = publication_hold_stamp != self._publication_hold_stamp
        self._publication_hold_stamp = publication_hold_stamp
        if changed:
            project = self._project
            files = tuple(
                _changed_files(project, self._inspection, changed)
                if project is not None and self._inspection is not None
                else ()
            )
            self._reinspect_project(current)
            return SourceChange(kind="project", files=files)

        if notebook_change:
            return SourceChange(kind="project", files=())
        if state_space_change or publication_hold_change:
            return SourceChange(kind="project", files=())
        return None

    def _reload_workspace(self, *, rebind_selected: bool) -> bool:
        try:
            current = load_studio(self._studio.config_path)
        except (MarimoStudioError, OSError) as error:
            self._inspection = None
            self._inspection_error = error
            return False
        previous = self._project
        selected = (
            current.views.get(self._view_name) if self._view_name is not None else None
        )
        self._studio = current
        self._config_stamp = _config_stamp(self._studio)
        self._notebook_stamp = _path_stamp(self._studio.notebook)
        self._view_catalog = _view_catalog(self._studio)
        if rebind_selected or _project_identity(previous) != _project_identity(
            selected
        ):
            self._bind_project(selected)
        else:
            self._project = selected
        return True

    def _select_project(self) -> None:
        project = (
            self._studio.views.get(self._view_name)
            if self._view_name is not None
            else None
        )
        self._bind_project(project)

    def _bind_project(self, project: ViewProject | None) -> None:
        self._project = project
        self._inspection = None
        self._input_id = None
        self._inspection_error = None
        self._roots = ()
        self._scope_files = ()
        self._excluded_roots = ()
        self._tree = {}
        self._catalog_stamps = {}
        if project is None:
            self._manifest_stamp = "missing"
            self._state_space_stamp = "missing"
            self._publication_hold_stamp = None
            return
        self._manifest_stamp = _optional_stamp(project.manifest)
        self._state_space_stamp = _optional_stamp(state_space_path(project.root))
        self._publication_hold_stamp = _publication_hold_stamp(project)
        self._reinspect_project()

    def _reinspect_project(
        self,
        observed_tree: dict[_WatchKey, _TreeStamp] | None = None,
    ) -> None:
        project = self._project
        if project is None:
            return
        self._inspection = None
        self._inspection_error = None
        try:
            registry = provider_registry()
            project = registry.validate_project(project)
            self._project = project
            provider = registry.get(project.provider)
            inspection = provider.inspect(inspection_request(project))
            input_files, roots = _validated_input_scope(project, inspection)
            document_files = _validated_document_files(project, inspection)
            scope_files = tuple(dict.fromkeys((*input_files, *document_files)))
            excluded_roots = (artifact_root(project),)
            if (
                observed_tree is not None
                and scope_files == self._scope_files
                and roots == self._roots
                and excluded_roots == self._excluded_roots
            ):
                tree = observed_tree
            else:
                tree = _tree_stamps((*scope_files, *roots), excluded_roots)
            inputs = _input_paths_from_tree(project, input_files, roots, tree)
            input_id = project_revision(
                project,
                inspection,
                provider.provenance(inspection),
                input_paths=inputs,
            )
        except Exception as error:
            raise_process_cleanup(error)
            # A third-party inspection failure must leave a safe path that can
            # observe the source repair which makes the next inspection valid.
            self._inspection_error = error
            repair_tree = observed_tree
            if not self._roots:
                self._scope_files = ()
                self._roots = (project.root,)
                self._excluded_roots = (artifact_root(project),)
                repair_tree = None
            scope = (*self._scope_files, *self._roots)
            self._tree = (
                repair_tree
                if repair_tree is not None
                else _tree_stamps(scope, self._excluded_roots)
            )
            self._catalog_stamps = _catalog_stamps(
                project,
                (),
                scope,
                self._tree,
            )
            return
        self._inspection = inspection
        self._input_id = input_id
        self._manifest_stamp = _optional_stamp(project.manifest)
        self._inspection_error = None
        self._scope_files = scope_files
        self._roots = roots
        self._excluded_roots = excluded_roots
        self._tree = tree
        self._catalog_stamps = _catalog_stamps(
            project,
            inputs,
            (*scope_files, *roots),
            self._tree,
        )


def _publication_hold_stamp(project: ViewProject) -> tuple[str, str] | None:
    hold = read_publication_hold(project.root)
    return (hold.token, hold.status) if hold is not None else None


def _project_identity(project: ViewProject | None) -> object:
    if project is None:
        return None
    return (
        project.root,
        project.provider,
        tuple(sorted(project.options.items())),
    )


def _path_stamp(
    path: Path,
    *,
    content_hashing: bool | None = None,
) -> _FileStamp:
    state = path.stat()
    metadata = (
        state.st_mtime_ns,
        state.st_ctime_ns,
        state.st_size,
        state.st_ino,
    )
    should_hash = os.name == "nt" if content_hashing is None else content_hashing
    if (
        not should_hash
        or not stat.S_ISREG(state.st_mode)
        or state.st_size > PROJECT_INPUT_BUDGET.max_file_bytes
    ):
        return metadata
    try:
        return digest_secure_file(
            path.parent,
            path,
            "Watched source file",
            max_bytes=PROJECT_INPUT_BUDGET.max_file_bytes,
        )
    except ConfigurationError:
        return metadata


def _optional_stamp(path: Path) -> _FileStamp:
    try:
        return _path_stamp(path)
    except OSError:
        return "missing"


def _stat_stamp(path: Path) -> _StatStamp:
    try:
        state = path.lstat()
    except OSError:
        return "missing"
    return (
        state.st_mode,
        state.st_mtime_ns,
        state.st_ctime_ns,
        state.st_size,
        state.st_ino,
    )


def _catalog_stamps(
    project: ViewProject,
    inputs: tuple[PurePosixPath, ...],
    roots: tuple[Path, ...],
    tree: dict[_WatchKey, _TreeStamp],
) -> dict[Path, _StatStamp]:
    project_root = project.root.absolute()
    paths = {project_root, project.manifest.absolute()}

    def include(path: Path) -> None:
        current = path.absolute()
        paths.add(current)
        while current != project_root and project_root in current.parents:
            current = current.parent
            paths.add(current)

    for path in inputs:
        include(project.root.joinpath(*path.parts))
    for root in roots:
        include(root)
    for (kind, path), stamp in tree.items():
        if kind == "root" and stamp == "directory":
            paths.add(path.absolute())
    return {path: _stat_stamp(path) for path in paths}


def _config_stamp(studio: StudioWorkspace) -> _FileStamp:
    if not studio.uses_notebook_config:
        return _optional_stamp(studio.config_path)
    try:
        config = notebook_config(studio.config_path)
    except (OSError, ConfigurationError):
        return _optional_stamp(studio.config_path)
    return hashlib.sha256(repr(config).encode("utf-8")).hexdigest()


def _view_catalog(studio: StudioWorkspace) -> _StructuralStamp:
    try:
        directories = tuple(
            path
            for path in studio.view_root.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
    except OSError:
        return ()
    records: list[tuple[str, _FileStamp | Literal["symlink"]]] = []
    for directory in sorted(directories, key=lambda path: path.name):
        manifest = directory / "view.toml"
        if manifest.is_symlink():
            records.append((directory.name, "symlink"))
        elif manifest.is_file():
            records.append((directory.name, _optional_stamp(manifest)))
    return tuple(records)


def _selected_manifest_transition(
    previous: _StructuralStamp,
    current: _StructuralStamp,
    view_name: str | None,
) -> bool:
    if view_name is None:
        return False
    before = dict(previous).get(view_name)
    after = dict(current).get(view_name)
    return before != after


def _validated_input_scope(
    project: ViewProject,
    inspection: ProjectInspection,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    root = project.root.resolve()
    files: list[Path] = []
    roots: list[Path] = []
    for item in inspection.input_scope:
        normalized = _scope_path(item.path, item.kind)
        if normalized.parts and normalized.parts[0].casefold() == ".artifacts":
            raise ConfigurationError("Provider input scope cannot include .artifacts")
        candidate = _validated_project_path(root, normalized, "Provider input scope")
        selected = roots if item.kind == "directory" else files
        if candidate not in selected:
            selected.append(candidate)
    return tuple(files), tuple(roots)


def _validated_document_files(
    project: ViewProject,
    inspection: ProjectInspection,
) -> tuple[Path, ...]:
    root = project.root.resolve()
    return tuple(
        dict.fromkeys(
            _validated_project_path(
                root,
                _scope_path(document.path, "file"),
                "Provider editor document",
            )
            for document in inspection.editor_documents
        )
    )


def _validated_project_path(
    root: Path,
    relative: PurePosixPath,
    label: str,
) -> Path:
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ConfigurationError(f"{label} contains a symlink: {relative}")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ConfigurationError(
            f"{label} escapes the view project: {relative}"
        ) from error
    return candidate


def _input_paths_from_tree(
    project: ViewProject,
    files: tuple[Path, ...],
    roots: tuple[Path, ...],
    tree: dict[_WatchKey, _TreeStamp],
) -> tuple[PurePosixPath, ...]:
    for path in files:
        if path.exists() and not path.is_file():
            raise ConfigurationError(f"View project input is not a file: {path}")
    for root in roots:
        if root.exists() and not root.is_dir():
            raise ConfigurationError(
                f"View project input root is not a directory: {root}"
            )
    symlink = next(
        (path for (_kind, path), stamp in tree.items() if stamp == "symlink"),
        None,
    )
    if symlink is not None:
        raise ConfigurationError(f"View project inputs contain a symlink: {symlink}")
    project_root = project.root.absolute()
    selected_files = {path.absolute() for path in files}
    selected_roots = tuple(path.absolute() for path in roots)
    inputs = {
        PurePosixPath(path.absolute().relative_to(project_root).as_posix())
        for (kind, path), _stamp in tree.items()
        if kind == "view"
        and (
            path.absolute() in selected_files
            or any(
                root == path.absolute() or root in path.absolute().parents
                for root in selected_roots
            )
        )
    }
    return tuple(sorted(inputs, key=PurePosixPath.as_posix))


def _scope_path(path: PurePosixPath, kind: str) -> PurePosixPath:
    if kind == "directory" and path == PurePosixPath("."):
        return path
    raw = path.as_posix()
    if (
        not raw
        or path.is_absolute()
        or "\\" in raw
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ConfigurationError(
            f"Provider input scope must use normalized project-relative paths: {raw}"
        )
    return path


def _tree_stamps(
    roots: tuple[Path, ...],
    excluded_roots: tuple[Path, ...] = (),
) -> dict[_WatchKey, _TreeStamp]:
    result: dict[_WatchKey, _TreeStamp] = {}
    excluded = {path.absolute() for path in excluded_roots}
    seen: set[Path] = set()
    cancellation = current_provider_cancellation()

    def cancelled() -> bool:
        return cancellation is not None and cancellation.cancelled

    for root in roots:
        if cancelled():
            raise ConfigurationError("Watched source scan was cancelled.")
        absolute_root = root.absolute()
        if absolute_root in excluded or absolute_root in seen:
            continue
        seen.add(absolute_root)
        if len(seen) > PROJECT_INPUT_BUDGET.max_files:
            raise ConfigurationError(
                "Watched source contains more than "
                f"{PROJECT_INPUT_BUDGET.max_files} entries. "
                "Remove files or split the project."
            )
        if root.is_symlink():
            result[("root", root)] = "symlink"
            continue
        if root.is_file():
            result[("view", root)] = _optional_stamp(root)
            continue
        if not root.is_dir():
            result[("root", root)] = "missing"
            continue
        result[("root", root)] = "directory"
        entries = bounded_tree_entries(
            root,
            max_entries=PROJECT_INPUT_BUDGET.max_files,
            label="Watched source",
            excluded_paths=excluded_roots,
            seen=seen,
            cancelled=cancelled,
        )
        for entry in entries:
            if entry.kind == "file":
                result[("view", entry.path)] = _optional_stamp(entry.path)
            else:
                result[("root", entry.path)] = entry.kind
    return result


def _changed_keys(
    previous: dict[_WatchKey, _TreeStamp],
    current: dict[_WatchKey, _TreeStamp],
) -> set[_WatchKey]:
    return {key for key, stamp in current.items() if previous.get(key) != stamp} | set(
        previous
    ).difference(current)


def _changed_files(
    project: ViewProject,
    inspection: ProjectInspection,
    changed: set[_WatchKey],
) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    documents = {document.path for document in inspection.editor_documents}
    for kind, path in sorted(changed, key=lambda item: str(item[1])):
        if kind != "view":
            continue
        try:
            relative = path.resolve(strict=False).relative_to(project.root.resolve())
        except ValueError:
            continue
        relative_path = PurePosixPath(relative.as_posix())
        if relative_path not in documents:
            continue
        source_name = relative.as_posix()
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            files.append({"path": source_name, "revision": None})
            continue
        except OSError:
            return []
        if not stat.S_ISREG(mode):
            return []
        try:
            revision = "sha256:" + digest_secure_file(
                project.root,
                path,
                "Changed source document",
                max_bytes=PROJECT_INPUT_BUDGET.max_file_bytes,
            )
        except (ConfigurationError, OSError):
            return []
        files.append({"path": source_name, "revision": revision})
    return files
