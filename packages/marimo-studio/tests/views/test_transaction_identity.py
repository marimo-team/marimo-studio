from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._filesystem._secure_types import (
    ConditionalWriteError,
    SecureFileError,
)
from marimo_studio._filesystem.io import read_file_snapshot_with_identity
from marimo_studio.errors import ConfigurationError


def test_file_transaction_rejects_a_changed_read_identity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"observed")
    _content, _mode, identity = read_file_snapshot_with_identity(target, root=root)
    target.write_bytes(b"concurrent")

    with (
        pytest.raises(ConfigurationError, match="changed"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"planned"},
            expected={target: identity},
        ),
    ):
        pass

    assert target.read_bytes() == b"concurrent"


def test_file_transaction_preserves_a_new_file_at_an_expected_absence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"concurrent")

    with (
        pytest.raises(ConfigurationError, match="changed"),
        workspace_transactions.write_file_transaction(
            root,
            {target: b"planned"},
            expected={target: None},
        ),
    ):
        pass

    assert target.read_bytes() == b"concurrent"


def test_file_transaction_rolls_back_a_replacement_after_identity_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    view = root / "views" / "dashboard"
    view.parent.mkdir(parents=True)
    config = root / "config.toml"
    config.write_bytes(b"original")
    _content, _mode, config_identity = read_file_snapshot_with_identity(
        config,
        root=root,
    )
    file_identity = secure_files.SecureDirectory.file_identity
    failed = False

    def fail_committed_identity(
        filesystem: secure_files.SecureDirectory,
        path: Path,
    ) -> secure_files.FileIdentity:
        nonlocal failed
        if path == config and not failed:
            failed = True
            raise PermissionError("identity unavailable")
        return file_identity(filesystem, path)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "file_identity",
        fail_committed_identity,
    )

    with (
        pytest.raises(ConditionalWriteError) as captured,
        workspace_transactions.write_file_transaction(
            root,
            {
                view / "index.html": b"<main>ready</main>",
                view / "view.toml": b'provider = "fixture"\n',
                config: b"configured",
            },
            expected={
                view / "index.html": None,
                view / "view.toml": None,
                config: config_identity,
            },
            claimed_directories={
                view: (
                    PurePosixPath("view.toml"),
                    PurePosixPath("index.html"),
                )
            },
        ),
    ):
        pass

    assert config.read_bytes() == b"original"
    assert not view.exists()
    assert captured.value.recovery is not None
    assert captured.value.recovery.read_bytes() == b"original"


def test_file_transaction_preserves_the_prior_source_after_publication_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    view = root / "views" / "dashboard"
    view.parent.mkdir(parents=True)
    config = root / "config.toml"
    config.write_bytes(b"original")
    _content, _mode, config_identity = read_file_snapshot_with_identity(
        config,
        root=root,
    )
    rename = secure_files.SecureDirectory.rename_if_absent
    raced = False

    def publish_external_destination(
        filesystem: secure_files.SecureDirectory,
        source: Path,
        destination: Path,
    ) -> None:
        nonlocal raced
        if (
            destination == config
            and source.name.startswith(".marimo-studio-cas-")
            and not raced
        ):
            raced = True
            destination.write_bytes(b"external")
        rename(filesystem, source, destination)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "rename_if_absent",
        publish_external_destination,
    )

    with (
        pytest.raises(ConditionalWriteError) as captured,
        workspace_transactions.write_file_transaction(
            root,
            {
                view / "index.html": b"<main>ready</main>",
                view / "view.toml": b'provider = "fixture"\n',
                config: b"configured",
            },
            expected={
                view / "index.html": None,
                view / "view.toml": None,
                config: config_identity,
            },
            claimed_directories={
                view: (
                    PurePosixPath("view.toml"),
                    PurePosixPath("index.html"),
                )
            },
        ),
    ):
        pass

    assert config.read_bytes() == b"external"
    assert not view.exists()
    assert captured.value.recovery is not None
    assert captured.value.recovery.read_bytes() == b"original"


def test_file_transaction_rejects_a_replaced_directory_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    view = root / "views" / "dashboard"
    view.parent.mkdir(parents=True)
    displaced = view.parent / "displaced-dashboard"
    create_directory = secure_files.SecureDirectory.create_directory
    swapped = False

    def swap_claim(
        filesystem: secure_files.SecureDirectory,
        path: Path,
        mode: int = 0o700,
    ) -> secure_files.FileIdentity:
        nonlocal swapped
        identity = create_directory(filesystem, path, mode)
        if path == view and not swapped:
            swapped = True
            path.rename(displaced)
            path.mkdir()
            path.joinpath("external.txt").write_text("external", encoding="utf-8")
        return identity

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "create_directory",
        swap_claim,
    )

    with (
        pytest.raises(SecureFileError, match="moved"),
        workspace_transactions.write_file_transaction(
            root,
            {
                view / "index.html": b"<main>ready</main>",
                view / "view.toml": b'provider = "fixture"\n',
            },
            expected={
                view / "index.html": None,
                view / "view.toml": None,
            },
            claimed_directories={
                view: (
                    PurePosixPath("view.toml"),
                    PurePosixPath("index.html"),
                )
            },
        ),
    ):
        pass

    assert view.joinpath("external.txt").read_text(encoding="utf-8") == "external"
    assert not view.joinpath("view.toml").exists()
    assert not view.joinpath("index.html").exists()
    assert displaced.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="Windows pins open directory paths")
def test_file_transaction_rejects_a_claim_swapped_during_final_identity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    view = root / "views" / "dashboard"
    view.parent.mkdir(parents=True)
    manifest = view / "view.toml"
    displaced = view.parent / "displaced-dashboard"
    file_identity = secure_files.SecureDirectory.file_identity
    identity_reads = 0
    swapped = False

    def swap_after_final_identity(
        filesystem: secure_files.SecureDirectory,
        path: Path,
    ) -> secure_files.FileIdentity:
        nonlocal identity_reads, swapped
        identity = file_identity(filesystem, path)
        if filesystem.root == view and path == manifest:
            identity_reads += 1
            if identity_reads == 2:
                swapped = True
                view.rename(displaced)
                view.mkdir()
                view.joinpath("external.txt").write_text(
                    "external",
                    encoding="utf-8",
                )
        return identity

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "file_identity",
        swap_after_final_identity,
    )

    with (
        pytest.raises(SecureFileError, match="moved"),
        workspace_transactions.write_file_transaction(
            root,
            {manifest: b'provider = "fixture"\n'},
            expected={manifest: None},
            claimed_directories={
                view: (PurePosixPath("view.toml"),),
            },
        ),
    ):
        pass

    assert view.joinpath("external.txt").read_text(encoding="utf-8") == "external"
    assert not view.joinpath("view.toml").exists()
    assert not displaced.joinpath("view.toml").exists()


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

    assert (directory / "external.txt").read_bytes() == b"external"
    assert "created" in " ".join(getattr(captured.value, "__notes__", ()))


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
