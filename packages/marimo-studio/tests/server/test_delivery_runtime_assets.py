from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app

from ..app_helpers import created_one_view


def test_runtime_asset_resolution_does_not_block_health_requests(
    notebook_path: Path,
    runtime_assets: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = created_one_view(notebook_path)
    started = threading.Event()
    release = threading.Event()
    resolve = Path.resolve

    def delayed_resolve(path: Path, strict: bool = False) -> Path:
        if path == runtime_assets:
            started.set()
            assert release.wait(timeout=2)
        return resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", delayed_resolve)
    with (
        TestClient(create_asgi_app(studio.notebook)) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        asset = executor.submit(
            client.get,
            "/_marimo-studio/assets/runtime.js",
        )
        assert started.wait(timeout=2)
        health = executor.submit(client.get, "/health")
        try:
            health_response = health.result(timeout=1)
        finally:
            release.set()
        asset_response = asset.result(timeout=2)

    assert health_response.status_code == 200
    assert asset_response.status_code == 200


def test_runtime_assets_preserve_range_head_and_cache_headers(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    studio = created_one_view(notebook_path)
    asset = runtime_assets / "range-test.js"
    asset.write_bytes(b"abcdef")
    try:
        with TestClient(create_asgi_app(studio.notebook)) as client:
            response = client.get("/_marimo-studio/assets/range-test.js")
            head = client.head("/_marimo-studio/assets/range-test.js")
            ranged = client.get(
                "/_marimo-studio/assets/range-test.js",
                headers={"Range": "bytes=1-3"},
            )
    finally:
        asset.unlink()

    assert response.status_code == 200
    assert response.content == b"abcdef"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["accept-ranges"] == "bytes"
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == "6"
    assert ranged.status_code == 206
    assert ranged.content == b"bcd"
    assert ranged.headers["content-range"] == "bytes 1-3/6"


def test_runtime_asset_route_rejects_missing_and_unsafe_paths(
    notebook_path: Path,
    runtime_assets: Path,
) -> None:
    studio = created_one_view(notebook_path)
    outside = runtime_assets.parent / "outside.js"
    alias = runtime_assets / "alias.js"
    outside.write_text("export {};\n", encoding="utf-8")
    alias.symlink_to(outside)
    try:
        with TestClient(create_asgi_app(studio.notebook)) as client:
            missing = client.get("/_marimo-studio/assets/missing.js")
            traversal = client.get(
                "/_marimo-studio/assets/%2e%2e/outside.js",
            )
            symlink = client.get("/_marimo-studio/assets/alias.js")
    finally:
        alias.unlink()
        outside.unlink()

    assert missing.status_code == 404
    assert traversal.status_code == 404
    assert symlink.status_code == 404
