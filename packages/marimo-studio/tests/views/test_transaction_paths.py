from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._filesystem._secure_names as secure_names
import marimo_studio._filesystem.secure as secure_files
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._filesystem.io import read_file_snapshot_with_identity
from marimo_studio._filesystem.paths import (
    PORTABLE_PATH_COMPONENT_MAX_BYTES,
    validate_portable_path_component,
)
from marimo_studio.errors import ConfigurationError

_MAX_COMPONENT_BYTES = PORTABLE_PATH_COMPONENT_MAX_BYTES


@pytest.mark.parametrize(
    "kind",
    (
        "cas",
        "claim",
        "delete",
        "detach",
        "export",
        "export-recovery",
        "restore",
        "rollback",
        "write",
    ),
)
@pytest.mark.supported_python
def test_transaction_sibling_names_are_windows_portable(
    monkeypatch: pytest.MonkeyPatch,
    kind: secure_names.TemporarySiblingKind,
) -> None:
    token = "ab" * 16
    monkeypatch.setattr(
        secure_names.secrets,
        "token_hex",
        lambda size: token if size == 16 else pytest.fail("unexpected token size"),
    )

    name = secure_names.temporary_sibling_name(kind)

    assert name == f".marimo-studio-{kind}-{token}"
    assert len(name.encode("utf-8")) < _MAX_COMPONENT_BYTES
    assert validate_portable_path_component(name, field="Transaction sibling") == name


@pytest.mark.supported_python
def test_rollback_sibling_collision_preserves_the_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "source.txt"
    target.write_bytes(b"source")
    first = "00" * 16
    second = "11" * 16
    tokens = iter((first, second))
    monkeypatch.setattr(secure_names.secrets, "token_hex", lambda _size: next(tokens))
    collision = root / f".marimo-studio-rollback-{first}"
    collision.write_bytes(b"sentinel")

    with secure_files.secure_directory(root) as filesystem:
        identity = filesystem.file_identity(target)
        recovery = filesystem.quarantine_if_identity(target, identity)

    assert collision.read_bytes() == b"sentinel"
    assert recovery.name == f".marimo-studio-rollback-{second}"
    assert recovery.read_bytes() == b"source"


@pytest.mark.supported_python
def test_file_transaction_creates_a_max_component_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / ("c" * _MAX_COMPONENT_BYTES)

    with workspace_transactions.write_file_transaction(
        root,
        {target: b"created"},
        expected={target: None},
    ):
        pass

    assert target.read_bytes() == b"created"
    assert not tuple(root.glob(".marimo-studio-*"))


@pytest.mark.supported_python
def test_secure_directory_creates_a_max_component_directory(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / ("d" * _MAX_COMPONENT_BYTES)

    with secure_files.secure_directory(root) as filesystem:
        identity = filesystem.create_directory(target)

    assert identity.directory
    assert target.is_dir()
    assert not tuple(root.glob(".marimo-studio-*"))


@pytest.mark.supported_python
def test_file_transaction_rolls_back_a_max_component_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    directory = root / ("q" * _MAX_COMPONENT_BYTES)
    document = directory / "index.html"

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(
            root,
            {document: b"created"},
            expected={document: None},
            claimed_directories={directory: (PurePosixPath("index.html"),)},
        ),
    ):
        raise RuntimeError("abort")

    assert not directory.exists()
    assert not tuple(root.glob(".marimo-studio-*"))


@pytest.mark.supported_python
def test_file_transaction_edits_a_max_component_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / ("e" * _MAX_COMPONENT_BYTES)
    target.write_bytes(b"before")
    _content, _mode, identity = read_file_snapshot_with_identity(target, root=root)

    with workspace_transactions.write_file_transaction(
        root,
        {target: b"after"},
        expected={target: identity},
    ):
        pass

    assert target.read_bytes() == b"after"
    assert not tuple(root.glob(".marimo-studio-*"))


@pytest.mark.supported_python
def test_file_transaction_rolls_back_a_max_component_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / ("b" * _MAX_COMPONENT_BYTES)
    target.write_bytes(b"before")

    with (
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(root, {target: b"after"}),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"before"
    assert not tuple(root.glob(".marimo-studio-*"))


@pytest.mark.supported_python
def test_file_transaction_preserves_max_component_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / ("r" * _MAX_COMPONENT_BYTES)
    target.write_bytes(b"before")

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
        pytest.raises(RuntimeError, match="abort"),
        workspace_transactions.write_file_transaction(root, {target: b"after"}),
    ):
        raise RuntimeError("abort")

    recoveries = tuple(root.glob(".marimo-studio-rollback-*"))
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == b"after"
    assert len(recoveries[0].name.encode("utf-8")) < _MAX_COMPONENT_BYTES


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
