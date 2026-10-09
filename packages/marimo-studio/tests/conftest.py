from __future__ import annotations

import ctypes
import errno
import json
import os
from collections.abc import Iterator
from pathlib import Path

import marimo
import pytest

import marimo_studio._delivery.assets as assets_module
import marimo_studio._filesystem._publish as publish
from marimo_studio._compat.layout import (
    MARIMO_FRONTEND_PATCH_SHA256,
    MARIMO_RELEASE_COMMIT,
)
from marimo_studio.view_providers._builtin._deno import runtime as deno_runtime

from .helpers import notebook_source


def _reject_exclusive_flag(*_args: object) -> int:
    ctypes.set_errno(errno.EINVAL)
    return -1


def _reject_hard_link(*_args: object, **_kwargs: object) -> None:
    raise OSError(errno.EIO, "hard links unavailable")


@pytest.fixture(
    params=[
        "native",
        pytest.param(
            "nfs",
            marks=pytest.mark.skipif(
                os.name == "nt", reason="Windows renames refuse existing paths"
            ),
        ),
        pytest.param(
            "object-storage",
            marks=pytest.mark.skipif(
                os.name == "nt", reason="Windows renames refuse existing paths"
            ),
        ),
    ]
)
def filesystem_shape(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Run a test on each filesystem shape that Studio supports.

    NFS, FUSE, WSL drive mounts, and gVisor host mounts reject
    RENAME_NOREPLACE with EINVAL. Object-storage FUSE mounts also refuse hard
    links, here with EIO as rclone reports it.
    """
    shape = str(request.param)
    if shape != "native":
        monkeypatch.setattr(
            publish,
            "_native_exclusive_rename",
            lambda: (_reject_exclusive_flag, 1),
        )
    if shape == "object-storage":
        monkeypatch.setattr(publish.os, "link", _reject_hard_link)
    return shape


@pytest.fixture(autouse=True)
def outside_marimohub() -> Iterator[None]:
    """Run each test outside a marimohub session unless the test publishes one.

    A private MonkeyPatch keeps the test's own ``monkeypatch`` teardown order,
    which module fixtures that restore process globals depend on.
    """
    with pytest.MonkeyPatch.context() as environment:
        environment.delenv("MARIMOHUB_CONTEXT_FILE", raising=False)
        environment.delenv("MARIMOHUB_KERNEL_URL", raising=False)
        yield


@pytest.fixture(autouse=True, scope="session")
def export_repository(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    repository = tmp_path_factory.mktemp("marimo-export-repository")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("MARIMO_EXPORT_REPOSITORY", str(repository))
    yield repository
    monkeypatch.undo()


@pytest.fixture(autouse=True, scope="session")
def runtime_assets(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    assets = tmp_path_factory.mktemp("runtime-assets")
    for name in (
        "runtime.js",
        "runtime.css",
        "zero-python.js",
        "zero-python.css",
        "dev-reload.js",
        "studio.js",
        "studio.css",
    ):
        (assets / name).write_text("", encoding="utf-8")
    assets.joinpath("zero-python.css").write_text(
        '.zero-root { background-image: url("./assets/zero-icon.svg"); }\n',
        encoding="utf-8",
    )
    assets.joinpath("zero-python.js").write_text(
        "globalThis.__ZERO_PYTHON_EVALUATIONS__ = "
        "(globalThis.__ZERO_PYTHON_EVALUATIONS__ ?? 0) + 1;\n"
        'import "./zero-python.css";\n'
        'import "./chunks/zero-theme.css";\n',
        encoding="utf-8",
    )
    assets.joinpath("chunks").mkdir()
    assets.joinpath("chunks/zero-runtime.js").write_text(
        'export const runtime = "zero";\n', encoding="utf-8"
    )
    assets.joinpath("chunks/zero-theme.css").write_text(
        '.zero-theme { mask-image: url("../assets/zero-icon.svg"); }\n',
        encoding="utf-8",
    )
    assets.joinpath("chunks/server-runtime.js").write_text(
        'export const runtime = "server";\n', encoding="utf-8"
    )
    assets.joinpath("chunks/pyodide-worker.js").write_text(
        'export const runtime = "worker";\n', encoding="utf-8"
    )
    assets.joinpath("chunks/wasm-runtime.js").write_text(
        'export const runtime = "wasm";\n', encoding="utf-8"
    )
    assets.joinpath("chunks/websocket-client.js").write_text(
        'export const runtime = "websocket";\n', encoding="utf-8"
    )
    assets.joinpath("chunks/notebook-source.js").write_text(
        'export const notebook = "source";\n', encoding="utf-8"
    )
    assets.joinpath("chunks/notebook-code.js").write_text(
        'export const notebook = "code";\n', encoding="utf-8"
    )
    assets.joinpath("assets").mkdir()
    assets.joinpath("assets/zero-icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8"
    )
    assets.joinpath("entry-closures.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "entries": {
                    "runtime": {
                        "script": "runtime.js",
                        "styles": ["runtime.css"],
                        "assets": [],
                    },
                    "zero-python": {
                        "script": "zero-python.js",
                        "styles": [
                            "zero-python.css",
                            "chunks/zero-theme.css",
                        ],
                        "assets": [
                            "chunks/zero-runtime.js",
                            "assets/zero-icon.svg",
                        ],
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (assets / "build-meta.json").write_text(
        json.dumps(
            {
                "marimo": {
                    "version": marimo.__version__,
                    "commit": MARIMO_RELEASE_COMMIT,
                    "patchSha256": MARIMO_FRONTEND_PATCH_SHA256,
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)
    yield assets
    monkeypatch.undo()


@pytest.fixture
def notebook_path(tmp_path: Path) -> Path:
    path = tmp_path / "analysis.py"
    path.write_text(
        notebook_source(tmp_path / "cell-executed"),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="session")
def deno_test_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("deno-cache")


@pytest.fixture
def shared_deno_test_cache(
    monkeypatch: pytest.MonkeyPatch,
    deno_test_cache: Path,
) -> None:
    ensure_cache_directory = deno_runtime.ensure_cache_directory
    monkeypatch.setattr(
        deno_runtime,
        "ensure_cache_directory",
        lambda _root, relative: ensure_cache_directory(
            deno_test_cache.resolve(),
            relative,
        ),
    )
