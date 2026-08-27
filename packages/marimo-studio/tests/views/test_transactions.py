"""Protect atomic workspace file transactions."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._filesystem import _secure_operations as secure_operations
from marimo_studio._filesystem._secure_types import ParentHandle
from marimo_studio.errors import ConfigurationError


def test_secure_directory_reports_a_missing_leaf_as_not_found(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with (
        secure_files.secure_directory(root) as filesystem,
        pytest.raises(FileNotFoundError),
    ):
        filesystem.open_file(root / "missing.txt")


def test_directory_tree_identity_tracks_contents_not_directory_timestamps(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    nested = root / "assets"
    nested.mkdir(parents=True)
    document = nested / "index.html"
    document.write_text("initial", encoding="utf-8")

    with secure_files.secure_directory(tmp_path) as filesystem:
        initial = filesystem.directory_tree_identity(root, max_entries=10)
        state = nested.stat()
        os.utime(
            nested,
            ns=(state.st_atime_ns, state.st_mtime_ns + 1_000_000_000),
        )
        touched = filesystem.directory_tree_identity(root, max_entries=10)
        document.write_text("changed content", encoding="utf-8")
        changed = filesystem.directory_tree_identity(root, max_entries=10)

    assert touched == initial
    assert changed != touched


def test_file_transaction_restores_a_colliding_file_tree_without_masking_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    collision = root / "collision"

    with (
        pytest.raises(ConfigurationError),
        workspace_transactions.write_file_transaction(
            root,
            {
                collision / "child.txt": b"child",
                collision: b"file",
            },
        ),
    ):
        pytest.fail("colliding writes must fail before the transaction body")

    assert not collision.exists()


def test_file_transaction_preserves_a_directory_at_a_write_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    ignore = root / ".gitignore"
    ignore.mkdir(parents=True)
    sentinel = ignore / "sentinel.txt"
    sentinel.write_text("owned\n", encoding="utf-8")

    with (
        pytest.raises(ConfigurationError, match="workspace file"),
        workspace_transactions.write_file_transaction(
            root,
            {ignore: ".locks/\n"},
        ),
    ):
        pytest.fail("directory write targets must fail before mutation")

    assert sentinel.read_text(encoding="utf-8") == "owned\n"


@pytest.mark.skipif(
    os.name == "nt", reason="Windows does not preserve POSIX file modes"
)
def test_file_transaction_restores_content_and_mode_after_rollback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    target = root / "script.sh"
    target.parent.mkdir()
    target.write_bytes(b"original\n")
    target.chmod(0o751)

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"replacement\n"},
        ),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"original\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o751


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_file_transaction_rollback_ignores_an_ancestor_swap_during_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"original")
    retired = tmp_path / "workspace-retired"
    external = tmp_path / "external"
    external.mkdir()
    (external / target.name).write_bytes(b"attacker")
    open_file = secure_files.os.open
    swapped = False

    def swap_root_during_open(
        selected: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(selected).name == target.name and dir_fd is not None and not swapped:
            swapped = True
            root.rename(retired)
            root.symlink_to(external, target_is_directory=True)
            descriptor = open_file(selected, flags, mode, dir_fd=dir_fd)
            root.unlink()
            retired.rename(root)
            return descriptor
        return open_file(selected, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(secure_files.os, "open", swap_root_during_open)

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"replacement"},
        ),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"original"
    assert (external / target.name).read_bytes() == b"attacker"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_file_transaction_keeps_nested_creation_and_rollback_in_its_open_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "nested" / "created.txt"
    retired = tmp_path / "workspace-retired"
    external = tmp_path / "external"
    external_target = external / "nested" / "created.txt"
    external_target.parent.mkdir(parents=True)
    external_target.write_bytes(b"external")
    open_file = secure_files.os.open
    swapped = False

    def swap_root_before_parent_creation(
        selected: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(selected).name == "nested" and dir_fd is not None and not swapped:
            swapped = True
            root.rename(retired)
            root.symlink_to(external, target_is_directory=True)
        return open_file(selected, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(secure_files.os, "open", swap_root_before_parent_creation)

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        raise RuntimeError("abort")

    assert external_target.read_bytes() == b"external"
    assert not (retired / "nested").exists()


def test_file_transaction_keeps_replaced_child_at_its_created_parent_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "nested" / "created.txt"

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        target.unlink()
        target.write_bytes(b"external")
        raise RuntimeError("abort")

    assert target.read_bytes() == b"external"
    assert "nested" in " ".join(getattr(captured.value, "__notes__", ()))


def test_file_transaction_preserves_directory_replaced_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outer = root / "outer"
    directory = outer / "created"
    target = directory / "source.txt"
    quarantine = secure_files.SecureDirectory.quarantine_directory_if_identity
    replaced = False

    def replace_before_quarantine(
        filesystem: secure_files.SecureDirectory,
        path: Path,
        expected: secure_files.FileIdentity,
    ) -> Path:
        nonlocal replaced
        if path == directory and not replaced:
            replaced = True
            path.rmdir()
            path.mkdir()
            (path / "external.txt").write_bytes(b"external")
        return quarantine(filesystem, path, expected)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "quarantine_directory_if_identity",
        replace_before_quarantine,
    )

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        raise RuntimeError("abort")

    quarantines = tuple(outer.glob(".created.rollback-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "external.txt").read_bytes() == b"external"
    assert "created" in " ".join(getattr(captured.value, "__notes__", ()))


@pytest.mark.skipif(
    os.name == "nt", reason="Windows directory opens use native handles"
)
def test_file_transaction_removes_a_parent_created_before_a_deeper_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "a" / "b" / "created.txt"
    open_file = secure_files.os.open

    def fail_deeper_parent(
        selected: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(selected).name == "b" and dir_fd is not None:
            raise OSError("deeper parent failed")
        return open_file(selected, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(secure_files.os, "open", fail_deeper_parent)

    with (
        pytest.raises(OSError, match="deeper parent failed"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        pytest.fail("parent creation must fail before the transaction body")

    assert not (root / "a").exists()


def test_contained_file_operations_reject_parent_segment_escapes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    external = tmp_path / "external" / "victim.txt"
    external.parent.mkdir()
    external.write_bytes(b"external")
    escaped = root / "sub" / ".." / ".." / "external" / "victim.txt"

    with pytest.raises(secure_files.SecureFileError, match="parent segments"):
        secure_files.open_contained_file(root, escaped)
    with pytest.raises(secure_files.SecureFileError, match="parent segments"):
        secure_files.atomic_write_contained(root, escaped, b"escaped")
    with (
        pytest.raises(ConfigurationError, match="workspace file"),
        workspace_transactions.write_file_transaction(
            root,
            {escaped: b"escaped"},
        ),
    ):
        pytest.fail("escaped path must fail before the transaction body")

    assert external.read_bytes() == b"external"


def test_file_transaction_preserves_a_replacement_after_created_file_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "created.txt"
    write = workspace_transactions.atomic_write_bytes

    def replace_after_commit(
        path: Path,
        content: bytes,
        *,
        root: Path | None = None,
        filesystem: secure_files.SecureDirectory | None = None,
        mode: int | None = None,
    ) -> secure_files.FileIdentity:
        identity = write(
            path,
            content,
            root=root,
            filesystem=filesystem,
            mode=mode,
        )
        path.unlink()
        path.write_bytes(b"external")
        path.chmod(stat.S_IMODE(identity.mode))
        state = path.stat(follow_symlinks=False)
        return secure_files.FileIdentity(
            state.st_dev,
            state.st_ino,
            state.st_mode,
            state.st_size,
            identity.digest,
            False,
        )

    monkeypatch.setattr(
        workspace_transactions,
        "atomic_write_bytes",
        replace_after_commit,
    )

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"owned123"},
        ),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"external"
    assert "changed before rollback" in " ".join(
        getattr(captured.value, "__notes__", ())
    )


def test_file_transaction_preserves_a_newer_edit_over_an_existing_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"original")

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        target.unlink()
        target.write_bytes(b"external")
        raise RuntimeError("abort")

    assert target.read_bytes() == b"external"
    assert "changed before rollback" in " ".join(
        getattr(captured.value, "__notes__", ())
    )


def test_file_transaction_keeps_quarantine_when_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    targets = (root / "source-a.txt", root / "source-b.txt")
    for target in targets:
        target.write_bytes(b"original")

    def fail_restore(
        _filesystem: secure_files.SecureDirectory,
        _path: Path,
        _content: bytes,
        _mode: int,
    ) -> secure_files.FileIdentity:
        raise OSError("restore unavailable")

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "restore_file_if_absent",
        fail_restore,
    )

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction" for target in targets},
        ),
    ):
        raise RuntimeError("abort")

    quarantines = tuple(root.glob(".source-*.txt.rollback-*"))
    assert len(quarantines) == 2
    assert {path.read_bytes() for path in quarantines} == {b"transaction"}
    notes = " ".join(getattr(captured.value, "__notes__", ()))
    assert "source-a.txt" in notes
    assert "source-b.txt" in notes


def test_file_transaction_restores_without_hard_link_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"original")

    def reject_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOTSUP, "hard links unavailable")

    monkeypatch.setattr(secure_files.os, "link", reject_link)

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"original"


def test_file_transaction_preserves_newer_edit_without_hard_link_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"original")

    def reject_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOTSUP, "hard links unavailable")

    monkeypatch.setattr(secure_files.os, "link", reject_link)

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"transaction"},
        ),
    ):
        target.unlink()
        target.write_bytes(b"external")
        raise RuntimeError("abort")

    assert target.read_bytes() == b"external"
    assert "changed before rollback" in " ".join(
        getattr(captured.value, "__notes__", ())
    )


def test_atomic_write_does_not_report_failure_after_its_replace_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("before", encoding="utf-8")
    fsync = secure_files.os.fsync

    def reject_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("directory fsync unavailable")
        fsync(descriptor)

    monkeypatch.setattr(secure_files.os, "fsync", reject_directory_fsync)

    with workspace_transactions.write_file_transaction(
        tmp_path,
        {target: b"after"},
    ):
        pass

    assert target.read_bytes() == b"after"


def test_atomic_write_retries_a_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source.txt"
    target.write_bytes(b"before")
    native_replace = secure_operations.os.replace
    attempts = 0

    def replace(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(errno.EACCES, "sharing violation")
        native_replace(*args, **kwargs)

    monkeypatch.setattr(secure_operations.os, "name", "nt")
    monkeypatch.setattr(secure_operations.os, "replace", replace)
    monkeypatch.setattr(secure_operations.time, "sleep", lambda _interval: None)

    identity = secure_operations.atomic_write_at(
        ParentHandle(tmp_path, None),
        target,
        b"after",
    )

    assert attempts == 2
    assert identity.size == len(b"after")
    assert target.read_bytes() == b"after"
