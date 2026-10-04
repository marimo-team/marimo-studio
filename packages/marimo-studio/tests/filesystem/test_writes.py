from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import marimo_studio._filesystem._entry as entries_module
import marimo_studio._filesystem._windows as windows
import marimo_studio._filesystem.files as files
import marimo_studio._filesystem.names as names
from marimo_studio._filesystem.errors import FileAccessError, UnsafePathError
from marimo_studio._filesystem.files import ABSENT, ConditionalWriteError, FileTree
from marimo_studio._filesystem.paths import validate_portable_path_component

from ..helpers import link_directory
from .conftest import entries

pytestmark = pytest.mark.supported_python


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_write_creates_private_files_and_keeps_the_mode_on_replace(
    tree: FileTree,
) -> None:
    path = tree.root / "view.toml"

    created = tree.write(path, b"one")

    assert path.read_bytes() == b"one"
    assert created == tree.version(path)
    if os.name != "nt":
        assert _mode(path) == 0o600
        path.chmod(0o640)
        tree.write(path, b"two")
        assert _mode(path) == 0o640
    assert entries(tree.root) == {"view.toml"}


def test_write_if_absent_creates_a_new_file(shaped_tree: FileTree) -> None:
    path = shaped_tree.root / "view.toml"

    shaped_tree.write(path, b"created", expect=ABSENT)

    assert path.read_bytes() == b"created"
    assert entries(shaped_tree.root) == {"view.toml"}


def test_write_if_absent_keeps_an_existing_file(shaped_tree: FileTree) -> None:
    path = shaped_tree.root / "view.toml"
    path.write_bytes(b"concurrent edit")

    with pytest.raises(ConditionalWriteError):
        shaped_tree.write(path, b"created", expect=ABSENT)

    assert path.read_bytes() == b"concurrent edit"
    assert entries(shaped_tree.root) == {"view.toml"}


def test_write_with_a_matching_version_replaces_the_file(
    shaped_tree: FileTree,
) -> None:
    path = shaped_tree.root / "notebook.py"
    path.write_bytes(b"original")
    expected = shaped_tree.read(path, max_bytes=1024).version

    written = shaped_tree.write(path, b"replacement", expect=expected)

    assert path.read_bytes() == b"replacement"
    assert written == shaped_tree.version(path)
    assert entries(shaped_tree.root) == {"notebook.py"}


def test_write_with_a_stale_version_keeps_the_concurrent_edit(
    shaped_tree: FileTree,
) -> None:
    path = shaped_tree.root / "notebook.py"
    path.write_bytes(b"original")
    expected = shaped_tree.read(path, max_bytes=1024).version
    path.write_bytes(b"concurrent edit")

    with pytest.raises(ConditionalWriteError):
        shaped_tree.write(path, b"replacement", expect=expected)

    assert path.read_bytes() == b"concurrent edit"
    assert entries(shaped_tree.root) == {"notebook.py"}


def test_write_with_a_version_of_a_removed_file_is_refused(
    shaped_tree: FileTree,
) -> None:
    path = shaped_tree.root / "notebook.py"
    path.write_bytes(b"original")
    expected = shaped_tree.read(path, max_bytes=1024).version
    path.unlink()

    with pytest.raises(ConditionalWriteError):
        shaped_tree.write(path, b"replacement", expect=expected)

    assert not path.exists()
    assert entries(shaped_tree.root) == set()


def test_write_refuses_to_replace_a_directory(tree: FileTree) -> None:
    (tree.root / "dashboard").mkdir()

    with pytest.raises(UnsafePathError):
        tree.write(tree.root / "dashboard", b"text")

    assert (tree.root / "dashboard").is_dir()


def test_publish_moves_a_directory_tree(shaped_tree: FileTree) -> None:
    staged = shaped_tree.root / "staged"
    (staged / "assets").mkdir(parents=True)
    (staged / "assets" / "app.js").write_bytes(b"app")

    shaped_tree.publish(staged, shaped_tree.root / "dashboard")

    assert (shaped_tree.root / "dashboard" / "assets" / "app.js").read_bytes() == b"app"
    assert entries(shaped_tree.root) == {
        "dashboard",
        "dashboard/assets",
        "dashboard/assets/app.js",
    }


def test_publish_moves_into_a_name_outside_the_basic_multilingual_plane(
    tree: FileTree,
) -> None:
    source = tree.root / "draft.txt"
    source.write_bytes(b"draft")
    destination = tree.root / "notes \N{GRINNING FACE}" / "draft.txt"
    destination.parent.mkdir()

    tree.publish(source, destination)

    assert destination.read_bytes() == b"draft"
    assert entries(tree.root) == {
        destination.parent.name,
        f"{destination.parent.name}/draft.txt",
    }


def test_publish_keeps_an_existing_empty_directory(shaped_tree: FileTree) -> None:
    staged = shaped_tree.root / "staged"
    staged.mkdir()
    (staged / "view.toml").write_bytes(b"staged")
    (shaped_tree.root / "dashboard").mkdir()

    with pytest.raises(FileExistsError):
        shaped_tree.publish(staged, shaped_tree.root / "dashboard")

    assert entries(shaped_tree.root) == {"dashboard", "staged", "staged/view.toml"}


def test_publish_keeps_an_existing_file(shaped_tree: FileTree) -> None:
    staged = shaped_tree.root / "staged.txt"
    staged.write_bytes(b"staged")
    destination = shaped_tree.root / "source.txt"
    destination.write_bytes(b"concurrent edit")

    with pytest.raises(FileExistsError):
        shaped_tree.publish(staged, destination)

    assert staged.read_bytes() == b"staged"
    assert destination.read_bytes() == b"concurrent edit"


def test_remove_with_a_matching_tree_version_deletes_the_tree(
    shaped_tree: FileTree,
) -> None:
    view = shaped_tree.root / "dashboard"
    view.mkdir()
    (view / "index.html").write_bytes(b"<p>")
    expected = shaped_tree.tree_version(view, max_entries=10)
    assert expected is not None

    shaped_tree.remove(view, expect=expected)

    assert entries(shaped_tree.root) == set()


def test_remove_with_a_stale_tree_version_restores_the_tree(
    shaped_tree: FileTree,
) -> None:
    view = shaped_tree.root / "dashboard"
    view.mkdir()
    (view / "index.html").write_bytes(b"<p>")
    expected = shaped_tree.tree_version(view, max_entries=10)
    assert expected is not None
    (view / "notes.md").write_bytes(b"concurrent addition")

    with pytest.raises(ConditionalWriteError):
        shaped_tree.remove(view, expect=expected)

    assert entries(shaped_tree.root) == {
        "dashboard",
        "dashboard/index.html",
        "dashboard/notes.md",
    }


def _refuse_opening_displaced_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    error = OSError(errno.EMFILE, "Too many open files")
    open_descriptor = files.os.open
    open_handle = windows.open_file

    def refuse_descriptor(path: Any, *args: Any, **kwargs: Any) -> int:
        if ".marimo-studio-aside-" in os.fspath(path):
            raise error
        return open_descriptor(path, *args, **kwargs)

    def refuse_handle(path: Path, *args: Any, **kwargs: Any) -> int:
        if path.name.startswith(".marimo-studio-aside-"):
            raise error
        return open_handle(path, *args, **kwargs)

    monkeypatch.setattr(files.os, "open", refuse_descriptor)
    monkeypatch.setattr(windows, "open_file", refuse_handle)


def test_a_versioned_write_that_cannot_compare_keeps_the_file(
    tree: FileTree,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tree.root / "notebook.py"
    expected = tree.write(path, b"saved")
    _refuse_opening_displaced_entries(monkeypatch)

    with pytest.raises(FileAccessError, match="Too many open files"):
        tree.write(path, b"edited", expect=expected)

    assert path.read_bytes() == b"saved"
    assert entries(tree.root) == {"notebook.py"}


def test_remove_finishes_when_an_entry_disappears_during_removal(
    tree: FileTree,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = tree.root / "dashboard"
    (view / "assets").mkdir(parents=True)
    (view / "assets" / "app.js").write_bytes(b"app")
    (view / "index.html").write_bytes(b"<p>")
    unlink = files.os.unlink

    def lose_then_unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        # Another process removes the entry after Studio inspected it.
        unlink(path, *args, **kwargs)
        unlink(path, *args, **kwargs)

    monkeypatch.setattr(files.os, "unlink", lose_then_unlink)

    tree.remove(view)

    assert entries(tree.root) == set()


def test_remove_deletes_links_without_following_them(
    tree: FileTree,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"keep")
    view = tree.root / "dashboard"
    view.mkdir()
    link_directory(outside, view / "linked")

    tree.remove(view)

    assert entries(tree.root) == set()
    assert (outside / "keep.txt").read_bytes() == b"keep"


def test_remove_treats_a_missing_entry_as_removed(tree: FileTree) -> None:
    tree.remove(tree.root / "missing")

    assert entries(tree.root) == set()


def test_create_directory_is_exclusive(shaped_tree: FileTree) -> None:
    created = shaped_tree.create_directory(shaped_tree.root / "dashboard")

    with pytest.raises(FileExistsError):
        shaped_tree.create_directory(shaped_tree.root / "dashboard")

    assert created == shaped_tree.version(shaped_tree.root / "dashboard")


def test_ensure_directory_reports_only_new_directories(tree: FileTree) -> None:
    (tree.root / "studio").mkdir()

    created = tree.ensure_directory(tree.root / "studio" / "analysis" / ".locks")

    assert created == (
        tree.root / "studio" / "analysis",
        tree.root / "studio" / "analysis" / ".locks",
    )
    assert tree.ensure_directory(tree.root / "studio" / "analysis") == ()


def test_ensure_directory_refuses_a_file_in_the_way(tree: FileTree) -> None:
    (tree.root / "studio").write_bytes(b"not a directory")

    with pytest.raises(UnsafePathError):
        tree.ensure_directory(tree.root / "studio" / "analysis")


@pytest.mark.parametrize("kind", ["write", "aside", "stage"])
def test_temporary_names_are_portable_path_components(
    kind: names.TemporaryKind,
) -> None:
    name = names.temporary_name(kind)

    assert validate_portable_path_component(name, field="Temporary name") == name
    assert names.is_temporary_name(name)


def test_a_failed_directory_sync_does_not_fail_a_committed_write(
    tree: FileTree,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tree.root / "source.txt"
    fsync = files.os.fsync

    def refuse_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "directory fsync unavailable")
        fsync(descriptor)

    monkeypatch.setattr(files.os, "fsync", refuse_directory_sync)

    tree.write(path, b"after")

    assert path.read_bytes() == b"after"


@pytest.mark.skipif(os.name != "nt", reason="Windows antivirus holds new files open")
def test_a_windows_sharing_violation_is_retried(
    tree: FileTree,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tree.root / "source.txt"
    path.write_bytes(b"before")
    replace = files.os.replace
    attempts = 0

    def share_once(source: Any, destination: Any, **descriptors: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(errno.EACCES, "sharing violation")
        replace(source, destination, **descriptors)

    monkeypatch.setattr(files.os, "replace", share_once)
    monkeypatch.setattr(entries_module.time, "sleep", lambda _interval: None)

    tree.write(path, b"after")

    assert attempts == 2
    assert path.read_bytes() == b"after"


_CONTEND = """
import sys
from pathlib import Path
import marimo_studio._filesystem._publish as publish
from marimo_studio._filesystem.files import ConditionalWriteError, FileTree

root, worker, shape = Path(sys.argv[1]), sys.argv[2], sys.argv[4]
rounds = int(sys.argv[3])
if shape == "nfs":
    # Without an exclusive rename flag, publication takes the NFS fallback.
    publish._native_exclusive_rename = lambda: None
tree = FileTree(root)
paths = [root / f"shared-{round_}.txt" for round_ in range(rounds)]
expected = [tree.read(path).version for path in paths]
print("ready", flush=True)
for round_ in range(rounds):
    go = root / f"go-{round_}"
    while not go.exists():
        pass
    try:
        tree.write(paths[round_], worker.encode(), expect=expected[round_])
        print("won", flush=True)
    except ConditionalWriteError:
        print("lost", flush=True)
"""


def _line(worker: subprocess.Popen[str]) -> str:
    assert worker.stdout is not None
    return worker.stdout.readline().strip()


@pytest.mark.native_process
@pytest.mark.parametrize(
    "shape",
    [
        "native",
        pytest.param(
            "nfs",
            marks=pytest.mark.skipif(
                os.name == "nt", reason="Windows renames through handles"
            ),
        ),
    ],
)
def test_concurrent_versioned_writes_admit_one_writer(
    tmp_path: Path, shape: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    rounds, writers = 20, 8
    tree = FileTree(root)
    for round_ in range(rounds):
        tree.write(root / f"shared-{round_}.txt", b"original")
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _CONTEND, str(root), str(index), str(rounds), shape],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(writers)
    ]
    try:
        assert all(_line(worker) == "ready" for worker in workers)
        for round_ in range(rounds):
            (root / f"go-{round_}").write_bytes(b"")
            outcomes = [_line(worker) for worker in workers]
            assert sorted(outcomes) == ["lost"] * (writers - 1) + ["won"], (
                round_,
                outcomes,
            )
            winner = outcomes.index("won")
            assert (root / f"shared-{round_}.txt").read_bytes() == str(winner).encode()
            assert [path.name for path in root.glob(".marimo-studio-*")] == []
    finally:
        # Release writers still waiting on later rounds after a failed round.
        for round_ in range(rounds):
            (root / f"go-{round_}").write_bytes(b"")
        results = [worker.communicate(timeout=60) for worker in workers]
    assert all(worker.returncode == 0 for worker in workers), [
        stderr for _stdout, stderr in results
    ]
