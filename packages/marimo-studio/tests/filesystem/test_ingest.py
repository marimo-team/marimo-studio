from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._filesystem.budgets import FileBudget
from marimo_studio._filesystem.errors import UnsafePathError
from marimo_studio._filesystem.files import FileTree
from marimo_studio._filesystem.ingest import IngestedFile
from marimo_studio.errors import ConfigurationError

from .conftest import entries

pytestmark = pytest.mark.supported_python

_BUDGET = FileBudget(max_files=8, max_file_bytes=1024, max_total_bytes=4096)


def _ingest(
    tmp_path: Path, staging: Path, destination: Path
) -> tuple[IngestedFile, ...]:
    return FileTree(tmp_path).ingest(
        staging, destination, budget=_BUDGET, label="Build output"
    )


def _staging(tmp_path: Path) -> Path:
    staging = tmp_path / "staging"
    (staging / "assets").mkdir(parents=True)
    (staging / "index.html").write_bytes(b"<script src=assets/app.js></script>")
    (staging / "assets" / "app.js").write_bytes(b"console.log(1)")
    return staging


def test_ingest_copies_regular_files_with_digests(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    destination = tmp_path / "publication"

    files = _ingest(tmp_path, staging, destination)

    assert files == (
        IngestedFile(
            PurePosixPath("assets/app.js"),
            hashlib.sha256(b"console.log(1)").hexdigest(),
            14,
        ),
        IngestedFile(
            PurePosixPath("index.html"),
            hashlib.sha256(b"<script src=assets/app.js></script>").hexdigest(),
            35,
        ),
    )
    assert entries(destination) == {"assets", "assets/app.js", "index.html"}
    assert (destination / "assets" / "app.js").read_bytes() == b"console.log(1)"


def test_ingest_refuses_an_existing_destination(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    destination = tmp_path / "publication"
    destination.mkdir()

    with pytest.raises(FileExistsError):
        _ingest(tmp_path, staging, destination)


def test_ingest_refuses_a_link_in_the_build_output(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"secret")
    try:
        (staging / "assets" / "secret.txt").symlink_to(secret)
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")

    with pytest.raises(UnsafePathError):
        _ingest(tmp_path, staging, tmp_path / "publication")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX entries")
def test_ingest_refuses_a_special_file(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    try:
        os.mkfifo(staging / "pipe")
    except (AttributeError, OSError) as error:
        pytest.skip(f"Named pipes are unavailable: {error}")

    with pytest.raises(UnsafePathError):
        _ingest(tmp_path, staging, tmp_path / "publication")


def test_ingest_enforces_the_file_budget(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    (staging / "large.bin").write_bytes(b"x" * 1025)

    with pytest.raises(ConfigurationError, match="per-file limit"):
        _ingest(tmp_path, staging, tmp_path / "publication")


def _open_paths() -> list[Path]:
    """Return the paths this process holds open on Linux and macOS."""
    if sys.platform.startswith("linux"):
        return [
            Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            for descriptor in os.listdir("/proc/self/fd")
            if os.path.exists(f"/proc/self/fd/{descriptor}")
        ]
    if sys.platform == "darwin":
        import fcntl

        paths: list[Path] = []
        for descriptor in os.listdir("/dev/fd"):
            try:
                raw = fcntl.fcntl(int(descriptor), fcntl.F_GETPATH, bytes(1024))
            except OSError:
                continue
            paths.append(Path(os.fsdecode(raw.rstrip(b"\0"))))
        return paths
    return []


def test_a_refused_ingest_releases_the_destination(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    (staging / "large.bin").write_bytes(b"x" * 1025)
    destination = tmp_path / "publication"

    with pytest.raises(ConfigurationError, match="per-file limit"):
        _ingest(tmp_path, staging, destination)

    held = destination.resolve()
    assert [path for path in _open_paths() if held in (path, *path.parents)] == []
    # Windows refuses to delete a file that a leaked descriptor holds open.
    FileTree(tmp_path).remove(destination)
    assert not destination.exists()


def test_ingest_refuses_a_symlinked_build_output_root(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(staging, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")

    with pytest.raises(UnsafePathError, match="symlink"):
        _ingest(tmp_path, linked, tmp_path / "publication")
