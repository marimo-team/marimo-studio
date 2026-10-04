from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import marimo_studio._filesystem._locks as locks
from marimo_studio._filesystem.errors import ConcurrentChangeError, UnsafePathError
from marimo_studio._filesystem.files import FileTree

pytestmark = pytest.mark.supported_python

_HOLD_LOCK = """
import sys
from pathlib import Path
from marimo_studio._filesystem.files import FileTree

root, path = Path(sys.argv[1]), Path(sys.argv[2])
with FileTree(root).lock(path) as acquired:
    print("held" if acquired else "missed", flush=True)
    sys.stdin.readline()
"""


def test_a_held_lock_refuses_a_second_owner(tree: FileTree) -> None:
    path = tree.root / ".locks" / ".catalog.lock"

    with tree.lock(path) as first, tree.lock(path, blocking=False) as second:
        assert (first, second) == (True, False)

    with tree.lock(path, blocking=False) as third:
        assert third is True


@pytest.mark.native_process
def test_a_lock_held_by_another_process_refuses_this_process(tree: FileTree) -> None:
    path = tree.root / ".locks" / "dashboard.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK, str(tree.root), str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        with tree.lock(path, blocking=False) as acquired:
            assert acquired is False
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(timeout=30)

    with tree.lock(path, blocking=False) as acquired:
        assert acquired is True


def test_an_absent_lock_file_is_not_created_on_request(tree: FileTree) -> None:
    path = tree.root / ".artifacts" / ".build.lock"

    with tree.lock(path, create=False) as acquired:
        assert acquired is False

    assert not path.parent.exists()


def test_a_linked_lock_file_is_refused(tree: FileTree, tmp_path: Path) -> None:
    outside = tmp_path / "outside.lock"
    outside.write_bytes(b"")
    link = tree.root / "linked.lock"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")

    with pytest.raises(UnsafePathError), tree.lock(link):
        pass


def test_a_lock_file_replaced_before_acquisition_is_refused(
    tree: FileTree,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tree.root / ".locks" / ".catalog.lock"
    acquire = locks.acquire

    def acquire_then_replace(descriptor: int, *, blocking: bool) -> bool:
        acquired = acquire(descriptor, blocking=blocking)
        path.unlink()
        path.write_bytes(b"replacement")
        return acquired

    monkeypatch.setattr(locks, "acquire", acquire_then_replace)

    with (
        pytest.raises(ConcurrentChangeError, match="replaced before it was acquired"),
        tree.lock(path),
    ):
        pytest.fail("a replaced lock file must not be trusted")
