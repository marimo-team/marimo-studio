from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._filesystem import _secure_operations as secure_operations
from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._filesystem.io import read_file_snapshot_with_identity
from marimo_studio.errors import ConfigurationError


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


def test_file_transaction_rolls_back_after_replacement_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"observed")
    _content, _mode, identity = read_file_snapshot_with_identity(target, root=root)
    unlink = secure_files.SecureDirectory.unlink
    failed = False

    def fail_claim_cleanup(
        filesystem: secure_files.SecureDirectory,
        path: Path,
    ) -> None:
        nonlocal failed
        if not failed and path.name.startswith(".marimo-studio-rollback-"):
            failed = True
            raise OSError("claim cleanup failed")
        unlink(filesystem, path)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "unlink",
        fail_claim_cleanup,
    )

    with (
        pytest.raises(ConditionalWriteError) as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"planned"},
            expected={target: identity},
        ),
    ):
        pass

    assert target.read_bytes() == b"observed"
    assert captured.value.recovery is not None
    assert captured.value.recovery.read_bytes() == b"observed"


def test_file_transaction_cleans_a_directory_claim_after_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    view = root / "views" / "dashboard"
    view.parent.mkdir(parents=True)

    def fail_identity(_state: os.stat_result) -> secure_files.FileIdentity:
        raise PermissionError("identity unavailable")

    monkeypatch.setattr(secure_files, "_directory_identity", fail_identity)

    with (
        pytest.raises(PermissionError, match="identity unavailable"),
        workspace_transactions.write_file_transaction(
            root,
            {view / "view.toml": b'provider = "fixture"\n'},
            expected={view / "view.toml": None},
            claimed_directories={
                view: (PurePosixPath("view.toml"),),
            },
        ),
    ):
        pass

    assert not view.exists()
    assert not tuple(view.parent.glob(".marimo-studio-claim-*"))


def test_file_transaction_removes_a_partial_direct_absent_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "created.txt"
    fsync = secure_operations.os.fsync
    calls = 0
    failed = False

    def reject_hard_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EPERM, "hard links unavailable")

    def fail_direct_fsync(descriptor: int) -> None:
        nonlocal calls, failed
        calls += 1
        if calls == 2 and not failed:
            failed = True
            raise OSError("direct fsync failed")
        fsync(descriptor)

    monkeypatch.setattr(secure_operations.os, "link", reject_hard_link)
    monkeypatch.setattr(secure_operations.os, "fsync", fail_direct_fsync)

    with (
        pytest.raises(ConditionalWriteError) as captured,
        workspace_transactions.write_file_transaction(
            root,
            {target: b"planned"},
            expected={target: None},
        ),
    ):
        pass

    assert not target.exists()
    assert captured.value.recovery is not None
    assert captured.value.recovery.read_bytes() == b"planned"


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

    quarantines = tuple(root.glob(".marimo-studio-rollback-*"))
    assert len(quarantines) == 2
    assert {path.read_bytes() for path in quarantines} == {b"transaction"}
    notes = " ".join(getattr(captured.value, "__notes__", ()))
    assert "source-a.txt" in notes
    assert "source-b.txt" in notes
