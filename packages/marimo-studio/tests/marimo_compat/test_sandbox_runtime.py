"""Bind sandboxed notebook processes to the Studio running the server."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest
from marimo._environments.environment import Environment, launch
from marimo._session.app_host import pool
from marimo._session.managers import ipc

from marimo_studio._compat.server import sandbox_runtime
from marimo_studio._compat.server.sandbox_runtime import (
    PrivateSandboxRuntime,
    studio_runtime_requirements,
)
from marimo_studio._workspace import installation


def _installed(
    monkeypatch: pytest.MonkeyPatch,
    direct_url: dict[str, object] | None,
    *,
    deno: str | None = None,
) -> None:
    recorded = None if direct_url is None else json.dumps(direct_url)
    studio = SimpleNamespace(
        version="0.1.6",
        read_text=lambda name: recorded if name == "direct_url.json" else None,
    )

    def installed(name: str) -> SimpleNamespace:
        if name == "marimo-studio":
            return studio
        if name == "deno" and deno is not None:
            return SimpleNamespace(version=deno)
        raise PackageNotFoundError(name)

    monkeypatch.setattr(sandbox_runtime, "distribution", installed)
    monkeypatch.setattr(installation, "distribution", installed)


def test_sandboxed_kernel_launch_includes_the_running_studio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _installed(
        monkeypatch,
        {"url": tmp_path.as_uri(), "dir_info": {"editable": True}},
    )
    environment = Environment(
        python=str(tmp_path / "bin" / "python"),
        root=str(tmp_path),
        action="unchanged",
    )
    marimo_runtime = ipc.runtime_overlay().runtime

    handle = PrivateSandboxRuntime().open()
    try:
        kernel = ipc.runtime_overlay()
        app_host = pool.runtime_overlay()
        plan = launch(environment, ["-m", "marimo._ipc.launch_kernel"], overlay=kernel)
    finally:
        handle.close()

    assert kernel.requirements == (marimo_runtime, f"-e {tmp_path}")
    assert app_host.requirements == (marimo_runtime, f"-e {tmp_path}")
    layered = list(plan.argv[: plan.argv.index("--")])
    assert layered[-2:] == ["--with-editable", str(tmp_path)]


def test_closed_adapter_restores_marimo_overlay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _installed(
        monkeypatch,
        {"url": tmp_path.as_uri(), "dir_info": {"editable": True}},
    )
    native = ipc.runtime_overlay().requirements

    PrivateSandboxRuntime().open().close()

    assert ipc.runtime_overlay().requirements == native
    assert pool.runtime_overlay().requirements == native


@pytest.mark.parametrize(
    ("deno", "requirements"),
    (
        ("2.9.5", ("marimo-studio==0.1.6", "deno==2.9.5")),
        (None, ("marimo-studio==0.1.6",)),
    ),
    ids=("with-deno", "without-deno"),
)
def test_sandboxed_processes_build_with_the_server_deno(
    monkeypatch: pytest.MonkeyPatch,
    deno: str | None,
    requirements: tuple[str, ...],
) -> None:
    _installed(monkeypatch, None, deno=deno)

    assert studio_runtime_requirements() == requirements


def test_uninstalled_studio_layers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> SimpleNamespace:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(sandbox_runtime, "distribution", missing)
    monkeypatch.setattr(installation, "distribution", missing)

    assert studio_runtime_requirements() == ()
