from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._filesystem import _secure_operations as secure_operations
from marimo_studio._filesystem._secure_types import ParentHandle


@pytest.mark.native_process
@pytest.mark.skipif(os.name != "nt", reason="Windows owns directory sharing behavior")
def test_file_transaction_removes_a_claimed_root_on_windows_rollback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    view = root / "views" / "dashboard"
    view.parent.mkdir(parents=True)

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(
            root,
            {view / "view.toml": b'provider = "fixture"\n'},
            expected={view / "view.toml": None},
            claimed_directories={
                view: (PurePosixPath("view.toml"),),
            },
        ),
    ):
        raise RuntimeError("abort")

    assert not view.exists()


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

    def replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(errno.EACCES, "sharing violation")
        native_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(secure_operations.os, "name", "nt")
    monkeypatch.setattr(secure_operations.os, "replace", replace)
    monkeypatch.setattr(secure_operations.time, "sleep", lambda _interval: None)

    identity = secure_operations.atomic_write_at(
        ParentHandle(tmp_path, None),
        target,
        b"after",
    )

    assert identity.size == len(b"after")
    assert target.read_bytes() == b"after"
