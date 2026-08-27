"""Fetch and verify the immutable NGA example datasets."""

from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import os
import shutil
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

DATASET_REVISION = "e19fc9a6bf8167630be458f745dfff915fbe06ba"
DATASET_BASE_URL = (
    "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/"
    f"{DATASET_REVISION}/data"
)
DATASET_IDENTITIES = {
    "objects.csv": (
        82_048_742,
        "de2df28d6211a2a88dba3dca9c3c916e8e23db4b4a084e47917c9ab78b029101",
    ),
    "constituents.csv": (
        4_472_583,
        "a192cdcad23ad0034f68227db46857b1f1b8903a32c935fb71a0de53d48f6f31",
    ),
    "published_images.csv": (
        89_211_268,
        "602894eb862d0aa9aeb59540efac282a050975f9a40d07250ce894c168b01985",
    ),
    "objects_constituents.csv": (
        38_935_425,
        "9911c0ad5fc37b1c213b1f599818df984273f338cd52ff0d1c27e7f011d8fbf4",
    ),
}
DATASET_FILES = tuple(DATASET_IDENTITIES)


def dataset_url(filename: str) -> str:
    return f"{DATASET_BASE_URL}/{filename}"


def prepare_dataset_paths(cache_root: Path | None = None) -> dict[str, Path]:
    root = cache_root or _default_cache_root()
    root.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(DATASET_FILES)) as pool:
        return dict(pool.map(lambda name: _cached_dataset(name, root), DATASET_FILES))


def read_dataset(
    pl: Any,
    paths: dict[str, Path],
    filename: str,
    **options: object,
) -> Any:
    with _decoded_payload(paths[filename]) as source:
        return pl.read_csv(source, **options)


def _default_cache_root() -> Path:
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_home / "marimo-studio" / "nga" / DATASET_REVISION


def _cached_dataset(
    filename: str,
    cache_root: Path,
    identity: tuple[int, str] | None = None,
) -> tuple[str, Path]:
    expected = identity or DATASET_IDENTITIES[filename]
    cached = cache_root / f"{filename}.payload"
    lock = cache_root / f".{filename}.lock"
    with _cache_lock(lock):
        if _payload_matches(cached, expected):
            return filename, cached
        cached.unlink(missing_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=cache_root,
                prefix=f".{filename}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                request = urllib.request.Request(
                    dataset_url(filename),
                    headers={"Accept-Encoding": "gzip"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    shutil.copyfileobj(response, temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
            if not _payload_matches(temporary_path, expected):
                raise OSError(f"Downloaded NGA dataset failed verification: {filename}")
            try:
                os.link(temporary_path, cached)
            except FileExistsError:
                if not _payload_matches(cached, expected):
                    raise OSError(f"Cached NGA dataset failed verification: {filename}")
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return filename, cached


def _payload_matches(path: Path, expected: tuple[int, str]) -> bool:
    if not path.is_file():
        return False
    size = 0
    digest = hashlib.sha256()
    try:
        with _decoded_payload(path) as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
    except (EOFError, OSError):
        return False
    return (size, digest.hexdigest()) == expected


@contextmanager
def _decoded_payload(path: Path) -> Iterator[BinaryIO]:
    with path.open("rb") as payload:
        compressed = payload.read(2) == b"\x1f\x8b"
        payload.seek(0)
        if compressed:
            with gzip.GzipFile(fileobj=payload) as source:
                yield source
        else:
            yield payload


@contextmanager
def _cache_lock(path: Path) -> Iterator[None]:
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            while True:
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


__all__ = [
    "DATASET_BASE_URL",
    "DATASET_REVISION",
    "dataset_url",
    "prepare_dataset_paths",
    "read_dataset",
]
