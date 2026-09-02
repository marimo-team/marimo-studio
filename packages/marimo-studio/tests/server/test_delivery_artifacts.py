from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._artifacts.retention import ArtifactLease, LeasedArtifactFile
from marimo_studio._views.build import build_view_project_sync

from ..app_helpers import configured as _configured
from ..artifact_test_support import add_provider_outputs as _add_provider_outputs
from .app_test_support import _artifact_base, _presentation_fallback_url


def test_large_artifact_get_streams_bounded_chunks_and_head_releases_lease(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    payload = b"x" * (64 * 1024 + 1)
    view = studio.views["dashboard"]
    _add_provider_outputs(
        monkeypatch,
        view,
        {PurePosixPath("large.bin"): payload},
    )
    entry = view.root / "index.html"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with build_view_project_sync(view):
        pass
    opened: list[LeasedArtifactFile] = []
    chunk_sizes: list[int] = []
    open_file = ArtifactLease.open_file
    iter_bytes = LeasedArtifactFile.iter_bytes

    def track_open(
        lease: ArtifactLease,
        path: str | PurePosixPath,
    ) -> LeasedArtifactFile:
        result = open_file(lease, path)
        opened.append(result)
        return result

    def track_chunks(file: LeasedArtifactFile) -> Iterator[bytes]:
        for chunk in iter_bytes(file):
            chunk_sizes.append(len(chunk))
            yield chunk

    monkeypatch.setattr(ArtifactLease, "open_file", track_open)
    monkeypatch.setattr(LeasedArtifactFile, "iter_bytes", track_chunks)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        page = client.get("/")
        presentation = client.get(_presentation_fallback_url(page.text))
        asset_url = f"{_artifact_base(presentation.text)}large.bin"
        head = client.head(asset_url)
        chunks_after_head = len(chunk_sizes)
        downloaded = client.get(asset_url)

    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(payload))
    assert chunks_after_head == 0
    assert downloaded.content == payload
    assert chunk_sizes
    assert max(chunk_sizes) <= 64 * 1024
    assert opened
    assert all(file.closed and file.lease.closed for file in opened)


def test_large_artifact_stream_does_not_block_unrelated_requests(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    payload = b"x" * (64 * 1024 + 1)
    view = studio.view("dashboard")
    _add_provider_outputs(
        monkeypatch,
        view,
        {PurePosixPath("large.bin"): payload},
    )
    entry = view.root / "index.html"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with build_view_project_sync(view):
        pass
    started = threading.Event()
    release = threading.Event()
    iterate = LeasedArtifactFile.iter_bytes

    def pause(file: LeasedArtifactFile) -> Iterator[bytes]:
        for index, chunk in enumerate(iterate(file)):
            if index == 0:
                started.set()
                assert release.wait(timeout=2)
            yield chunk

    monkeypatch.setattr(LeasedArtifactFile, "iter_bytes", pause)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        page = client.get("/")
        presentation = client.get(_presentation_fallback_url(page.text))
        asset_url = f"{_artifact_base(presentation.text)}large.bin"
        with ThreadPoolExecutor(max_workers=1) as executor:
            download = executor.submit(client.get, asset_url)
            assert started.wait(timeout=2)
            health = client.get("/health")
            assert not download.done()
            release.set()
            streamed = download.result(timeout=2)

    assert health.status_code == 200
    assert streamed.content == payload


def test_nested_vanilla_entry_keeps_sibling_files_private(notebook_path: Path) -> None:
    studio = _configured(notebook_path)
    view = studio.views["dashboard"]
    pages = view.root / "pages"
    pages.mkdir()
    entrypoint = pages / "index.html"
    entrypoint.write_text(
        (view.root / "index.html")
        .read_text(encoding="utf-8")
        .replace(
            "</head>",
            '<script>window.nestedAsset = "ready";</script></head>',
        ),
        encoding="utf-8",
    )
    (pages / "app.js").write_text('window.nestedAsset = "ready";\n', encoding="utf-8")
    view.manifest.write_text(
        view.manifest.read_text(encoding="utf-8")
        + '\n[options]\nentrypoint = "pages/index.html"\n',
        encoding="utf-8",
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        page = client.get("/")
        presentation = client.get(_presentation_fallback_url(page.text))
        base = _artifact_base(presentation.text)
        asset = client.get(f"{base}app.js")

    assert page.status_code == 200
    assert base.endswith("/pages/")
    assert asset.status_code == 404
