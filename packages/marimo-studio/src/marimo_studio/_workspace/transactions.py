"""Apply related workspace file writes as one recoverable operation."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from marimo_studio._filesystem.errors import UnsafePathError
from marimo_studio._filesystem.files import (
    ABSENT,
    ConditionalWriteError,
    Expectation,
    FileTree,
    Snapshot,
    TreeVersion,
    Version,
)
from marimo_studio.errors import ConfigurationError, WorkspaceMutationError


def _changed(path: Path) -> ConfigurationError:
    return ConfigurationError(
        f"Workspace path changed before the transaction committed: {path}. "
        "Run the operation again."
    )


def _add_error_note(error: BaseException, note: str) -> None:
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(note)
        return
    notes: list[str] = list(getattr(error, "__notes__", ()))
    notes.append(note)
    error.__notes__ = notes  # pyright: ignore[reportAttributeAccessIssue]


def _owning_directory(path: Path, directories: Collection[Path]) -> Path | None:
    owners = [directory for directory in directories if directory in path.parents]
    return max(owners, key=lambda item: len(item.parts)) if owners else None


def _entry_count(directory: Path, files: Collection[Path]) -> int:
    entries: set[Path] = set()
    for file in files:
        entries.add(file)
        entries.update(parent for parent in file.parents if directory in parent.parents)
    return len(entries)


def _tree_version(tree: FileTree, directory: Path, entries: int) -> TreeVersion | None:
    # A tree that gained entries or a link no longer matches what was published.
    try:
        return tree.tree_version(directory, max_entries=entries)
    except UnsafePathError:
        return None


class _Undo:
    """Record each committed change so a failure can restore prior state."""

    def __init__(self, tree: FileTree) -> None:
        self._tree = tree
        self._steps: list[tuple[Path, Callable[[], None]]] = []

    def ensure_directory(self, directory: Path) -> None:
        """Create missing directories through ``directory`` and undo each one.

        Each level is created and recorded before the next, so a failure
        deeper in the chain still removes the levels this transaction created.
        """
        current = self._tree.root
        for component in directory.relative_to(self._tree.root).parts:
            current /= component
            for created in self._tree.ensure_directory(current):
                self._steps.append(
                    (created, lambda path=created: self._remove_created(path))
                )

    def _remove_created(self, directory: Path) -> None:
        # A created directory that gained entries holds someone else's files.
        if not self._tree.remove_empty_directory(directory) and self._tree.exists(
            directory
        ):
            raise ConditionalWriteError(
                f"Directory gained entries before rollback: {directory}"
            )

    def published(self, directory: Path, version: TreeVersion) -> None:
        self._steps.append(
            (directory, lambda: self._tree.remove(directory, expect=version))
        )

    def wrote(self, path: Path, previous: Snapshot | None, written: Version) -> None:
        def restore() -> None:
            if previous is None:
                self._tree.remove(path, expect=written)
            else:
                self._tree.write(
                    path,
                    previous.content,
                    expect=written,
                    mode=previous.mode,
                )

        self._steps.append((path, restore))

    def rollback(self) -> None:
        failures: list[tuple[Path, Exception]] = []
        for path, restore in reversed(self._steps):
            try:
                restore()
            except Exception as error:
                failures.append((path, error))
        if failures:
            details = "\n".join(f"- {path}: {error}" for path, error in failures)
            raise RuntimeError(
                f"Workspace rollback failures:\n{details}"
            ) from failures[0][1]


@contextmanager
def write_file_transaction(
    root: Path,
    writes: Mapping[Path, str | bytes],
    *,
    expected: Mapping[Path, Version | None] | None = None,
    new_directories: Collection[Path] = (),
) -> Iterator[None]:
    """Write related files under ``root`` and restore prior state after a failure.

    ``expected`` maps a path to the version the caller read, or to ``None``
    when the path must stay absent. Expectations hold before the first write
    and again after the ``with`` body. A written path with an expectation
    commits only while it still matches. Every directory in
    ``new_directories`` must be absent. Its files from ``writes`` are staged
    together and published with one rename.

    A failed write, failed expectation, or exception in the body restores
    everything this transaction committed. Content that changed after this
    transaction wrote it stays in place, and the rollback error names it.
    """
    tree = FileTree(root)
    expectations = dict(expected or {})
    staged: dict[Path, dict[Path, bytes]] = {
        directory: {} for directory in new_directories
    }
    direct: dict[Path, bytes] = {}
    for path, content in writes.items():
        payload = content.encode("utf-8") if isinstance(content, str) else content
        owner = _owning_directory(path, new_directories)
        if owner is None:
            direct[path] = payload
        else:
            staged[owner][path] = payload
    previous: dict[Path, Snapshot | None] = {}
    for path in direct:
        try:
            previous[path] = tree.read(path)
        except FileNotFoundError:
            previous[path] = None
    for path, version in expectations.items():
        if path in previous:
            snapshot = previous[path]
            current = snapshot.version if snapshot is not None else None
        else:
            current = tree.version(path)
        if current != version:
            raise _changed(path)
    undo = _Undo(tree)
    committed = {
        path: version for path, version in expectations.items() if path not in writes
    }
    published: dict[Path, tuple[TreeVersion, int]] = {}
    try:
        for directory, files in sorted(
            staged.items(), key=lambda item: len(item[0].parts)
        ):
            undo.ensure_directory(directory.parent)
            entries = _entry_count(directory, files)
            with tree.temporary_directory(directory.parent) as staging:
                for path, payload in files.items():
                    target = staging / path.relative_to(directory)
                    tree.ensure_directory(target.parent)
                    tree.write(target, payload)
                # A rename keeps every inode, so the staged tree's version is
                # the published tree's version.
                version = tree.tree_version(staging, max_entries=entries)
                if version is None:
                    raise _changed(directory)
                try:
                    tree.publish(staging, directory)
                except FileExistsError as error:
                    raise _changed(directory) from error
            undo.published(directory, version)
            published[directory] = (version, entries)
        for path, payload in direct.items():
            undo.ensure_directory(path.parent)
            expect: Expectation = None
            if path in expectations:
                expectation = expectations[path]
                expect = ABSENT if expectation is None else expectation
            try:
                written = tree.write(path, payload, expect=expect)
            except ConditionalWriteError as error:
                if error.committed is not None:
                    undo.wrote(path, previous[path], error.committed)
                raise
            undo.wrote(path, previous[path], written)
            committed[path] = written
        yield
        for path, version in committed.items():
            if tree.version(path) != version:
                raise _changed(path)
        for directory, (version, entries) in published.items():
            if _tree_version(tree, directory, entries) != version:
                raise _changed(directory)
    except BaseException as error:
        try:
            undo.rollback()
        except BaseException as rollback_error:
            _add_error_note(error, f"Workspace rollback also failed: {rollback_error}")
        raise


@contextmanager
def workspace_transaction(
    operation: str,
    root: Path,
    writes: Mapping[Path, str | bytes],
    *,
    expected: Mapping[Path, Version | None],
    new_directories: Collection[Path] = (),
) -> Iterator[None]:
    """Run one named workspace mutation as a file transaction.

    A conditional write that fails once the transaction began raises
    ``WorkspaceMutationError``, so the caller reloads before retrying.
    """
    try:
        with write_file_transaction(
            root,
            writes,
            expected=expected,
            new_directories=new_directories,
        ):
            yield
    except ConditionalWriteError as error:
        raise WorkspaceMutationError(
            operation,
            recovery=error.recovery,
            write_committed=error.committed is not None,
        ) from error
