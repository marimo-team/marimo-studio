"""Identify and copy the exact view inputs that a provider may build.

A project revision combines the view name, provider package identity, provider
build semantics, explicit view options, ``view.toml``, and every file in the
bounded input scope returned by inspection. Generated artifact state stays
outside that identity, so a build output cannot make its own source appear
changed.

Studio compares each input before and after reading it, then copies the exact
bytes into an isolated build directory. If any input changes during capture,
the operation fails. Builds, source writes, presentation capture, cache reuse,
and export use this revision so one result cannot combine different versions
of the authored files.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import BinaryIO, cast

from marimo_studio._artifacts.limits import (
    PROJECT_INPUT_BUDGET,
    FileBudgetTracker,
)
from marimo_studio._artifacts.paths import (
    artifact_root,
    assert_secure_path,
    normalized_artifact_path,
    verified_secure_file,
)
from marimo_studio._filesystem.secure import SecureDirectory, secure_directory
from marimo_studio._filesystem.tree import bounded_tree_entries
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    JsonValue,
    ProjectInspection,
    ViewProject,
)
from marimo_studio.view_providers._host.records import ProviderProvenance

_InputEntry = tuple[PurePosixPath, Path, str]
_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ProjectSnapshot:
    project: ViewProject
    input_digests: Mapping[PurePosixPath, bytes]


@dataclass(frozen=True)
class ProjectInputFileState:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class ProjectInputState:
    paths: tuple[PurePosixPath, ...]
    files: Mapping[PurePosixPath, ProjectInputFileState]
    directories: Mapping[PurePosixPath, tuple[int, int, int, int, int]]
    absent: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class ProjectRevisionSnapshot:
    revision: str
    state: ProjectInputState


def _input_entry(project: ViewProject, value: PurePosixPath) -> _InputEntry:
    relative = normalized_artifact_path(
        value.as_posix(),
        "View project input path",
    )
    if relative.parts[0] == ".artifacts":
        raise ConfigurationError(
            "View project inputs must not include artifact control files"
        )
    return relative, project.root.joinpath(*relative.parts), "View project input"


def _bounded_chunks(
    stream: BinaryIO,
    size: int,
    path: Path,
    label: str,
) -> Iterator[bytes]:
    remaining = size
    while remaining:
        chunk = stream.read(min(_CHUNK_BYTES, remaining))
        if not chunk:
            raise ConfigurationError(f"{label} changed while it was read: {path}")
        remaining -= len(chunk)
        yield chunk
    if stream.read(1):
        raise ConfigurationError(f"{label} changed while it was read: {path}")


def _capture_entry(
    root: Path,
    entry: _InputEntry,
    budget: FileBudgetTracker,
    output: BinaryIO | None = None,
) -> bytes:
    relative, path, label = entry
    digest = hashlib.sha256()
    with verified_secure_file(root, path, label) as (stream, state):
        budget.add(relative.as_posix(), state.st_size)
        for chunk in _bounded_chunks(stream, state.st_size, path, label):
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
    return digest.digest()


def _identity(
    project: ViewProject,
    provenance: ProviderProvenance,
) -> bytes:
    try:
        return json.dumps(
            {
                "name": project.name,
                "provider": provenance.to_dict(),
                "options": dict(project.options),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise ConfigurationError(
            f"View project {project.name!r} has non-canonical options"
        ) from error


def _revision_from_digests(
    project: ViewProject,
    provenance: ProviderProvenance,
    input_digests: Mapping[PurePosixPath, bytes],
) -> str:
    digest = hashlib.sha256(_identity(project, provenance))
    for path in sorted(input_digests, key=PurePosixPath.as_posix):
        relative, _path, _label = _input_entry(project, path)
        try:
            input_digest = input_digests[relative]
        except KeyError as error:
            raise ConfigurationError(
                f"View project input was not captured: {relative}"
            ) from error
        digest.update(b"\0")
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(input_digest)
    return f"sha256:{digest.hexdigest()}"


def project_input_paths(
    project: ViewProject,
    inspection: ProjectInspection,
) -> tuple[PurePosixPath, ...]:
    """Enumerate one provider input scope through Studio's file budget."""
    return _input_catalog(project, inspection)[0]


def _input_catalog(
    project: ViewProject,
    inspection: ProjectInspection,
) -> tuple[
    tuple[PurePosixPath, ...], tuple[PurePosixPath, ...], tuple[PurePosixPath, ...]
]:
    cancellation = current_provider_cancellation()
    paths: set[PurePosixPath] = set()
    directories: set[PurePosixPath] = set()
    absent: set[PurePosixPath] = set()
    seen_entries: set[Path] = set()
    for item in inspection.input_scope:
        target = project.root.joinpath(*item.path.parts)
        if not target.exists() and not target.is_symlink():
            absent.add(item.path)
            continue
        if item.kind == "file":
            paths.add(item.path)
            continue
        directories.add(item.path)
        discovered = bounded_tree_entries(
            target,
            max_entries=PROJECT_INPUT_BUDGET.max_files,
            label="View project inputs",
            excluded_paths=(artifact_root(project),),
            seen=seen_entries,
            cancelled=(
                (lambda: cancellation.cancelled) if cancellation is not None else None
            ),
        )
        for entry in discovered:
            relative = PurePosixPath(entry.path.relative_to(project.root).as_posix())
            if entry.kind == "symlink":
                raise ConfigurationError(
                    f"View project inputs contain a symlink: {entry.path}"
                )
            (directories if entry.kind == "directory" else paths).add(relative)
    ordered = tuple(sorted(paths, key=PurePosixPath.as_posix))
    FileBudgetTracker(PROJECT_INPUT_BUDGET, "View project inputs").require_count(
        len(ordered)
    )
    return (
        ordered,
        tuple(sorted(directories, key=PurePosixPath.as_posix)),
        tuple(sorted(absent, key=PurePosixPath.as_posix)),
    )


def _manifest_path(project: ViewProject) -> PurePosixPath:
    try:
        return normalized_artifact_path(
            project.manifest.relative_to(project.root).as_posix(),
            "View project manifest path",
        )
    except ValueError as error:
        raise ConfigurationError(
            f"View project manifest is outside {project.root}: {project.manifest}"
        ) from error


def _input_state_with_owner(
    project: ViewProject,
    inspection: ProjectInspection,
    files: SecureDirectory,
    observed: ProjectInputState | None = None,
) -> ProjectInputState:
    files.ensure_attached()
    if observed is None:
        input_paths, directory_paths, absent = _input_catalog(project, inspection)
        paths = tuple(
            sorted({*input_paths, _manifest_path(project)}, key=PurePosixPath.as_posix)
        )
    else:
        paths = observed.paths
        directory_paths = tuple(observed.directories)
        missing: list[PurePosixPath] = []
        for relative in observed.absent:
            try:
                present = files.entry_exists(project.root.joinpath(*relative.parts))
            except FileNotFoundError:
                present = False
            if not present:
                missing.append(relative)
        absent = tuple(missing)
    directories: dict[PurePosixPath, tuple[int, int, int, int, int]] = {}
    for relative in directory_paths:
        path = project.root.joinpath(*relative.parts)
        with secure_directory(path) as directory:
            directory.ensure_attached()
            state = path.stat(follow_symlinks=False)
            directory.ensure_attached()
        directories[relative] = (
            state.st_dev,
            state.st_ino,
            state.st_mode,
            state.st_mtime_ns,
            state.st_ctime_ns,
        )
    states: dict[PurePosixPath, ProjectInputFileState] = {}
    for relative in paths:
        path = project.root.joinpath(*relative.parts)
        descriptor = files.open_file(path)
        try:
            state = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if not stat.S_ISREG(state.st_mode):
            raise ConfigurationError(f"View project input is not a file: {path}")
        states[relative] = ProjectInputFileState(
            state.st_dev,
            state.st_ino,
            state.st_mode,
            state.st_size,
            state.st_mtime_ns,
            state.st_ctime_ns,
        )
    files.ensure_attached()
    return ProjectInputState(
        paths, MappingProxyType(states), MappingProxyType(directories), absent
    )


def project_input_state(
    project: ViewProject,
    inspection: ProjectInspection,
    *,
    files: SecureDirectory | None = None,
    observed: ProjectInputState | None = None,
) -> ProjectInputState:
    """Capture bounded input metadata without reading file contents."""
    if files is not None:
        return _input_state_with_owner(project, inspection, files, observed)
    with secure_directory(project.root) as owner:
        return _input_state_with_owner(project, inspection, owner, observed)


def project_revision_snapshot(
    project: ViewProject,
    inspection: ProjectInspection,
    provenance: ProviderProvenance,
) -> ProjectRevisionSnapshot:
    """Capture one coherent content revision and its cheap revalidation state."""
    revision_paths = project_input_paths(project, inspection)
    expected_state_paths = tuple(
        sorted({*revision_paths, _manifest_path(project)}, key=PurePosixPath.as_posix)
    )
    before = project_input_state(project, inspection)
    if before.paths != expected_state_paths:
        raise ConfigurationError(
            f"View project {project.name!r} changed while its inputs were captured"
        )
    revision = project_revision(
        project,
        inspection,
        provenance,
        input_paths=revision_paths,
    )
    after = project_input_state(project, inspection)
    if before != after:
        raise ConfigurationError(
            f"View project {project.name!r} changed while its inputs were captured"
        )
    return ProjectRevisionSnapshot(revision, after)


def project_revision(
    project: ViewProject,
    inspection: ProjectInspection,
    provenance: ProviderProvenance,
    *,
    input_paths: tuple[PurePosixPath, ...] | None = None,
) -> str:
    """Hash the project contract and every declared, contained input."""
    paths = (
        project_input_paths(project, inspection)
        if input_paths is None
        else tuple(sorted(set(input_paths), key=PurePosixPath.as_posix))
    )
    entries = tuple(_input_entry(project, path) for path in paths)
    budget = FileBudgetTracker(PROJECT_INPUT_BUDGET, "View project inputs")
    budget.require_count(len(entries))
    input_digests: dict[PurePosixPath, bytes] = {}
    for entry in entries:
        input_digests[entry[0]] = _capture_entry(project.root, entry, budget)
    return _revision_from_digests(project, provenance, input_digests)


def snapshot_project(
    project: ViewProject,
    inspection: ProjectInspection,
    snapshot_root: Path,
) -> ProjectSnapshot:
    """Copy declared project inputs into a private build root."""
    assert_secure_path(project.root, snapshot_root, "View input snapshot")
    with secure_directory(project.root) as project_files:
        project_files.ensure_directory(snapshot_root)
    assert_secure_path(
        project.root,
        snapshot_root,
        "View input snapshot",
        final_kind="directory",
    )
    manifest_relative = _manifest_path(project)
    before = project_input_state(project, inspection)
    entries = tuple(_input_entry(project, path) for path in before.paths)
    budget = FileBudgetTracker(PROJECT_INPUT_BUDGET, "View project inputs")
    budget.require_count(len(entries))
    input_digests: dict[PurePosixPath, bytes] = {}
    with secure_directory(snapshot_root) as snapshot_files:
        for relative, source, label in entries:
            destination = snapshot_root.joinpath(*relative.parts)
            snapshot_files.ensure_parent(destination)
            with os.fdopen(snapshot_files.create_file(destination), "wb") as output:
                input_digests[relative] = _capture_entry(
                    project.root,
                    (relative, source, label),
                    budget,
                    output,
                )
    manifest = snapshot_root.joinpath(*manifest_relative.parts)
    options = cast(
        Mapping[str, JsonValue],
        json.loads(
            json.dumps(
                dict(project.options),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        ),
    )
    after = project_input_state(project, inspection)
    if before != after:
        raise ConfigurationError(
            f"View project {project.name!r} changed while its snapshot was captured"
        )
    return ProjectSnapshot(
        ViewProject(
            name=project.name,
            root=snapshot_root,
            manifest=manifest,
            provider=project.provider,
            options=options,
        ),
        MappingProxyType(input_digests),
    )


def snapshot_revision(
    snapshot: ProjectSnapshot,
    provenance: ProviderProvenance,
) -> str:
    """Return the project identity captured while its snapshot was copied."""
    return _revision_from_digests(
        snapshot.project,
        provenance,
        snapshot.input_digests,
    )
