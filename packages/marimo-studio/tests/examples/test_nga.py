"""Protect the NGA notebook and view projects."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from marimo_studio._workspace import load_studio

_EXAMPLES = Path(__file__).parents[4] / "examples"


def _load_nga_data() -> ModuleType:
    source = _EXAMPLES / "_nga_data.py"
    spec = importlib.util.spec_from_file_location("marimo_studio_nga_data", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity(content: bytes) -> tuple[int, str]:
    return len(content), hashlib.sha256(content).hexdigest()


class _Response(io.BytesIO):
    pass


def test_nga_overview_is_the_single_document_vanilla_example() -> None:
    project = load_studio(_EXAMPLES / "nga.py").view("overview")
    authored = tuple(
        sorted(
            path.relative_to(project.root).as_posix()
            for path in project.root.rglob("*")
            if path.is_file()
            and ".artifacts" not in path.relative_to(project.root).parts
            and path.name != "view.toml"
        )
    )
    document = project.root / "index.html"
    source = document.read_text(encoding="utf-8")

    assert project.provider == "marimo-studio/vanilla"
    assert project.options == {}
    assert authored == ("index.html",)
    assert "<style>" in source
    assert '<script type="module">' in source


def _download_temps(root: Path) -> list[Path]:
    return [
        path
        for path in root.iterdir()
        if path.name.startswith(".sample.csv.") and not path.name.endswith(".lock")
    ]


def test_nga_cache_rejects_a_truncated_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nga = _load_nga_data()
    content = b"column\n" + b"value\n" * 1_000
    payload = gzip.compress(content, mtime=0)
    monkeypatch.setattr(
        nga.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(payload[: len(payload) // 2]),
    )

    with pytest.raises(OSError, match="failed verification"):
        nga._cached_dataset("sample.csv", tmp_path, _identity(content))

    assert not (tmp_path / "sample.csv.payload").exists()
    assert not _download_temps(tmp_path)


def test_nga_cache_repairs_a_corrupt_hit_before_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nga = _load_nga_data()
    content = b"column\nvalid\n"
    payload = gzip.compress(content, mtime=0)
    cached = tmp_path / "sample.csv.payload"
    cached.write_bytes(b"truncated")
    downloads = 0

    def download(*_args: object, **_kwargs: object) -> _Response:
        nonlocal downloads
        downloads += 1
        return _Response(payload)

    monkeypatch.setattr(nga.urllib.request, "urlopen", download)
    first = nga._cached_dataset("sample.csv", tmp_path, _identity(content))
    second = nga._cached_dataset("sample.csv", tmp_path, _identity(content))

    assert first == second == ("sample.csv", cached)
    assert downloads == 1
    assert gzip.decompress(cached.read_bytes()) == content


def test_nga_cache_serializes_concurrent_writers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nga = _load_nga_data()
    content = b"column\nconcurrent\n"
    payload = gzip.compress(content, mtime=0)
    downloads = 0
    download_lock = threading.Lock()
    download_started = threading.Event()
    release_download = threading.Event()

    def download(*_args: object, **_kwargs: object) -> _Response:
        nonlocal downloads
        with download_lock:
            downloads += 1
        download_started.set()
        assert release_download.wait(timeout=2)
        return _Response(payload)

    monkeypatch.setattr(nga.urllib.request, "urlopen", download)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            nga._cached_dataset,
            "sample.csv",
            tmp_path,
            _identity(content),
        )
        assert download_started.wait(timeout=2)
        second = pool.submit(
            nga._cached_dataset,
            "sample.csv",
            tmp_path,
            _identity(content),
        )
        release_download.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert results == [
        ("sample.csv", tmp_path / "sample.csv.payload"),
        ("sample.csv", tmp_path / "sample.csv.payload"),
    ]
    assert downloads == 1
    assert gzip.decompress(results[0][1].read_bytes()) == content


def test_nga_cache_keeps_a_valid_concurrent_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nga = _load_nga_data()
    content = b"column\nwinner\n"
    payload = gzip.compress(content, mtime=0)
    cached = tmp_path / "sample.csv.payload"
    monkeypatch.setattr(
        nga.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    def publish_winner(_source: Any, destination: Path) -> None:
        destination.write_bytes(payload)
        raise FileExistsError

    monkeypatch.setattr(nga.os, "link", publish_winner)

    result = nga._cached_dataset("sample.csv", tmp_path, _identity(content))

    assert result == ("sample.csv", cached)
    assert gzip.decompress(cached.read_bytes()) == content
    assert not _download_temps(tmp_path)
