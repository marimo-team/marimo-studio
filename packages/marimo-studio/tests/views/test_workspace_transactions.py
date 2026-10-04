from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import Any

import pytest

import marimo_studio._filesystem.files as files
from marimo_studio._filesystem.files import (
    ConditionalWriteError,
    FileTree,
    Version,
)
from marimo_studio._filesystem.paths import PORTABLE_PATH_COMPONENT_MAX_BYTES
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import ConfigurationError


def _notes(error: BaseException) -> str:
    return " ".join(getattr(error, "__notes__", ()))


def _version(path: Path) -> Version:
    version = FileTree(path.parent).version(path)
    assert version is not None
    return version


@pytest.fixture
def root(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _leftovers(root: Path) -> list[str]:
    return [path.name for path in root.rglob(".marimo-studio-*")]


# Preconditions


def test_transaction_refuses_a_file_changed_after_it_was_read(root: Path) -> None:
    target = root / "source.txt"
    target.write_bytes(b"observed")
    observed = _version(target)
    target.write_bytes(b"concurrent")

    with (
        pytest.raises(ConfigurationError, match="changed"),
        write_file_transaction(root, {target: b"planned"}, expected={target: observed}),
    ):
        pytest.fail("a stale expectation must fail before the body")

    assert target.read_bytes() == b"concurrent"


def test_transaction_keeps_a_file_created_at_an_expected_absence(root: Path) -> None:
    target = root / "source.txt"
    target.write_bytes(b"concurrent")

    with (
        pytest.raises(ConfigurationError, match="changed"),
        write_file_transaction(root, {target: b"planned"}, expected={target: None}),
    ):
        pytest.fail("an occupied absence must fail before the body")

    assert target.read_bytes() == b"concurrent"


def test_transaction_refuses_a_directory_at_a_write_target(root: Path) -> None:
    ignore = root / ".gitignore"
    ignore.mkdir()
    (ignore / "sentinel.txt").write_text("owned\n", encoding="utf-8")

    with (
        pytest.raises(ConfigurationError, match="not a regular file"),
        write_file_transaction(root, {ignore: ".locks/\n"}),
    ):
        pytest.fail("a directory write target must fail before the body")

    assert (ignore / "sentinel.txt").read_text(encoding="utf-8") == "owned\n"


def test_transaction_refuses_a_path_that_leaves_its_root(
    root: Path, tmp_path: Path
) -> None:
    external = tmp_path / "external" / "victim.txt"
    external.parent.mkdir()
    external.write_bytes(b"external")
    escaped = root / "sub" / ".." / ".." / "external" / "victim.txt"

    with (
        pytest.raises(ConfigurationError, match="parent segments"),
        write_file_transaction(root, {escaped: b"escaped"}),
    ):
        pytest.fail("an escaping path must fail before the body")

    assert external.read_bytes() == b"external"


def test_transaction_supports_maximum_length_names(root: Path) -> None:
    target = root / ("c" * PORTABLE_PATH_COMPONENT_MAX_BYTES)
    directory = root / ("q" * PORTABLE_PATH_COMPONENT_MAX_BYTES)

    with write_file_transaction(root, {target: b"created"}, expected={target: None}):
        pass
    with write_file_transaction(
        root, {target: b"edited"}, expected={target: _version(target)}
    ):
        pass
    with (
        pytest.raises(RuntimeError, match="abort"),
        write_file_transaction(
            root,
            {target: b"temporary", directory / "index.html": b"created"},
            new_directories=(directory,),
        ),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"edited"
    assert not directory.exists()
    assert _leftovers(root) == []


# Rollback


@pytest.mark.skipif(os.name == "nt", reason="Windows does not keep POSIX modes")
def test_rollback_restores_content_and_mode(root: Path) -> None:
    target = root / "script.sh"
    target.write_bytes(b"original\n")
    target.chmod(0o751)

    with (
        pytest.raises(RuntimeError, match="abort"),
        write_file_transaction(root, {target: b"replacement\n"}),
    ):
        raise RuntimeError("abort")

    assert target.read_bytes() == b"original\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o751


def test_rollback_removes_created_files_and_parents(
    root: Path, filesystem_shape: str
) -> None:
    created = root / "a" / "b" / "created.txt"
    existing = root / "source.txt"
    existing.write_bytes(b"original")

    with (
        pytest.raises(RuntimeError, match="abort"),
        write_file_transaction(root, {created: b"created", existing: b"edited"}),
    ):
        raise RuntimeError("abort")

    assert not (root / "a").exists()
    assert existing.read_bytes() == b"original"
    assert _leftovers(root) == []


def test_rollback_keeps_a_newer_edit(root: Path, filesystem_shape: str) -> None:
    target = root / "source.txt"
    target.write_bytes(b"original")

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        write_file_transaction(root, {target: b"transaction"}),
    ):
        target.unlink()
        target.write_bytes(b"external")
        raise RuntimeError("abort")

    assert target.read_bytes() == b"external"
    assert "changed before" in _notes(captured.value)
    assert _leftovers(root) == []


def test_rollback_keeps_a_file_that_replaced_a_created_one(
    root: Path, filesystem_shape: str
) -> None:
    target = root / "nested" / "created.txt"

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        write_file_transaction(root, {target: b"transaction"}),
    ):
        target.unlink()
        target.write_bytes(b"external")
        raise RuntimeError("abort")

    assert target.read_bytes() == b"external"
    assert "nested" in _notes(captured.value)


def test_rollback_reports_every_file_it_could_not_restore(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = (root / "source-a.txt", root / "source-b.txt")
    for target in targets:
        target.write_bytes(b"original")
    write = FileTree.write

    def refuse_restore(
        tree: FileTree, path: Path, content: bytes, **options: Any
    ) -> Version:
        if content == b"original":
            raise OSError("restore unavailable")
        return write(tree, path, content, **options)

    monkeypatch.setattr(FileTree, "write", refuse_restore)

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        write_file_transaction(root, dict.fromkeys(targets, b"transaction")),
    ):
        raise RuntimeError("abort")

    notes = _notes(captured.value)
    assert "source-a.txt" in notes
    assert "source-b.txt" in notes


def test_colliding_writes_fail_and_roll_back(root: Path) -> None:
    collision = root / "collision"

    with (
        pytest.raises(ConfigurationError),
        write_file_transaction(
            root, {collision / "child.txt": b"child", collision: b"file"}
        ),
    ):
        pytest.fail("colliding writes must fail before the body")

    assert not collision.exists()


def test_a_failed_parent_creation_leaves_no_partial_parents(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mkdir = files.os.mkdir

    def refuse_deeper_parent(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == "b":
            raise PermissionError(errno.EACCES, "deeper parent refused")
        mkdir(path, *args, **kwargs)

    monkeypatch.setattr(files.os, "mkdir", refuse_deeper_parent)

    with (
        pytest.raises(OSError, match="deeper parent refused"),
        write_file_transaction(root, {root / "a" / "b" / "created.txt": b"x"}),
    ):
        pytest.fail("parent creation must fail before the body")

    monkeypatch.undo()
    assert not (root / "a").exists()


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_rollback_never_follows_a_root_swapped_for_a_symlink(
    root: Path, tmp_path: Path
) -> None:
    target = root / "source.txt"
    target.write_bytes(b"original")
    external = tmp_path / "external"
    external.mkdir()
    (external / "source.txt").write_bytes(b"attacker")
    (external / "created").mkdir()
    retired = tmp_path / "retired"

    with (
        pytest.raises(RuntimeError, match="abort") as captured,
        write_file_transaction(
            root, {target: b"transaction", root / "created" / "new.txt": b"new"}
        ),
    ):
        root.rename(retired)
        root.symlink_to(external, target_is_directory=True)
        raise RuntimeError("abort")

    assert (external / "source.txt").read_bytes() == b"attacker"
    assert tuple((external / "created").iterdir()) == ()
    assert "symlink" in _notes(captured.value)


# Conditional commits


def test_a_cleanup_failure_after_commit_restores_and_keeps_a_recovery_copy(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = root / "source.txt"
    target.write_bytes(b"observed")
    remove_entry = files._remove_entry
    failed = False

    def refuse_first_cleanup(entry: files.Entry) -> None:
        nonlocal failed
        if not failed and entry.path.name.startswith(".marimo-studio-aside-"):
            failed = True
            raise OSError("cleanup failed")
        remove_entry(entry)

    monkeypatch.setattr(files, "_remove_entry", refuse_first_cleanup)

    with (
        pytest.raises(ConditionalWriteError) as captured,
        write_file_transaction(
            root, {target: b"planned"}, expected={target: _version(target)}
        ),
    ):
        pytest.fail("a failed commit must not reach the body")

    assert target.read_bytes() == b"observed"
    assert captured.value.recovery is not None
    assert captured.value.recovery.read_bytes() == b"observed"


def test_a_file_published_during_the_swap_is_preserved(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    filesystem_shape: str,
) -> None:
    target = root / "config.toml"
    target.write_bytes(b"original")
    publish_entry = files.publish_entry
    raced = False

    def publish_external_first(source: files.Entry, destination: files.Entry) -> None:
        nonlocal raced
        if destination.path == target and not raced:
            raced = True
            target.write_bytes(b"external")
        publish_entry(source, destination)

    monkeypatch.setattr(files, "publish_entry", publish_external_first)

    with (
        pytest.raises(ConditionalWriteError) as captured,
        write_file_transaction(
            root, {target: b"configured"}, expected={target: _version(target)}
        ),
    ):
        pytest.fail("a lost publication race must not reach the body")

    assert target.read_bytes() == b"external"
    assert captured.value.recovery is not None
    assert captured.value.recovery.read_bytes() == b"original"


# New directories


def test_a_new_directory_appears_whole_after_commit(
    root: Path, filesystem_shape: str
) -> None:
    view = root / "views" / "dashboard"

    with write_file_transaction(
        root,
        {view / "view.toml": b'provider = "fixture"\n', view / "src" / "a.js": b"a"},
        new_directories=(view,),
    ):
        assert (view / "view.toml").is_file()
        assert (view / "src" / "a.js").is_file()

    assert _leftovers(root) == []


def test_a_new_directory_refuses_one_created_concurrently(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    filesystem_shape: str,
) -> None:
    view = root / "views" / "dashboard"
    publish = FileTree.publish

    def create_external_first(tree: FileTree, source: Path, destination: Path) -> None:
        if destination == view and not view.exists():
            view.mkdir()
            (view / "external.txt").write_text("external", encoding="utf-8")
        publish(tree, source, destination)

    monkeypatch.setattr(FileTree, "publish", create_external_first)

    with (
        pytest.raises(ConfigurationError, match="changed"),
        write_file_transaction(
            root, {view / "view.toml": b"x"}, new_directories=(view,)
        ),
    ):
        pytest.fail("a lost directory race must not reach the body")

    assert {path.name for path in view.iterdir()} == {"external.txt"}
    assert _leftovers(root) == []


def test_a_new_directory_swapped_during_the_body_fails_the_transaction(
    root: Path,
) -> None:
    view = root / "views" / "dashboard"
    displaced = root / "views" / "displaced"

    with (
        pytest.raises(ConfigurationError, match="changed"),
        write_file_transaction(
            root, {view / "view.toml": b"x"}, new_directories=(view,)
        ),
    ):
        view.rename(displaced)
        view.mkdir()
        (view / "external.txt").write_text("external", encoding="utf-8")

    assert (view / "external.txt").read_text(encoding="utf-8") == "external"


def test_a_file_added_to_a_published_directory_is_kept_and_named(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = root / "views" / "dashboard"
    publish = FileTree.publish

    def publish_then_add(tree: FileTree, source: Path, destination: Path) -> None:
        publish(tree, source, destination)
        if destination == view:
            (view / ".DS_Store").write_bytes(b"finder")

    monkeypatch.setattr(FileTree, "publish", publish_then_add)

    with (
        pytest.raises(ConfigurationError, match="changed") as raised,
        write_file_transaction(
            root, {view / "view.toml": b"x"}, new_directories=(view,)
        ),
    ):
        pass

    assert (view / ".DS_Store").read_bytes() == b"finder"
    assert str(view) in _notes(raised.value)


def test_a_failed_staging_write_leaves_no_directory(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = root / "views" / "dashboard"
    write = FileTree.write

    def refuse_manifest(
        tree: FileTree, path: Path, content: bytes, **options: Any
    ) -> Version:
        if path.name == "view.toml":
            raise OSError("staging failed")
        return write(tree, path, content, **options)

    monkeypatch.setattr(FileTree, "write", refuse_manifest)

    with (
        pytest.raises(OSError, match="staging failed"),
        write_file_transaction(
            root, {view / "view.toml": b"x"}, new_directories=(view,)
        ),
    ):
        pytest.fail("a failed staging write must not reach the body")

    assert not (root / "views").exists()
    assert _leftovers(root) == []
