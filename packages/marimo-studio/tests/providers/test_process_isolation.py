"""Protect third-party provider deadlines and process-tree ownership."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from importlib.metadata import EntryPoint
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import (
    BuildResult,
    JsonValue,
    ProjectInspection,
    ProviderCancellation,
    ProviderInfo,
    ProviderStarter,
    StarterContext,
    ViewProject,
)
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..provider_test_support import (
    ProviderStub,
    inspection,
)

pytestmark = pytest.mark.native_process

_PROCESS_START_TIMEOUT = 15.0

_IMPORT_MARKER = os.environ.get("MARIMO_STUDIO_PROVIDER_IMPORT_MARKER")
if _IMPORT_MARKER:
    marker = Path(_IMPORT_MARKER)
    marker.mkdir(parents=True, exist_ok=True)
    (marker / f"{os.getpid()}-{time.time_ns()}").touch()
if os.environ.get("MARIMO_STUDIO_PROVIDER_BLOCK") == "describe":
    threading.Event().wait(30)
_DISCOVERY_BARRIER = os.environ.get("MARIMO_STUDIO_PROVIDER_DISCOVERY_BARRIER")
if _DISCOVERY_BARRIER:
    barrier = Path(_DISCOVERY_BARRIER)
    with barrier.open("a", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()}\n")
    deadline = time.monotonic() + 2
    while (
        len(barrier.read_text(encoding="utf-8").splitlines()) < 2
        and time.monotonic() < deadline
    ):
        threading.Event().wait(0.01)
    if len(barrier.read_text(encoding="utf-8").splitlines()) < 2:
        threading.Event().wait(30)
    threading.Event().wait(
        float(os.environ.get("MARIMO_STUDIO_PROVIDER_DISCOVERY_DELAY", "0"))
    )


def _run_process_tree(request: Any) -> None:
    marker = Path(str(request.project.options["marker"]))
    marker.write_text(f"{os.getpid()}\n", encoding="utf-8")
    command = (
        "import os, pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(30)']); "
        f"marker = pathlib.Path({str(marker)!r}); "
        "stream = marker.open('a'); "
        "stream.write(f'{os.getpid()}\\n{child.pid}\\n'); "
        "stream.flush(); os.fsync(stream.fileno()); stream.close(); "
        "time.sleep(30)"
    )
    request.runner.run(
        [sys.executable, "-c", command],
        cwd=request.project.root,
        timeout=request.command_timeout,
    )


class _ProcessTreeProvider(ProviderStub):
    def inspect(self, request: Any):
        _run_process_tree(request)
        return inspection()


class _BuildProcessTreeProvider(ProviderStub):
    def build(self, request: Any):
        _run_process_tree(request)
        return super().build(request)


class _RuntimeProvider(ProviderStub):
    def build(self, request: Any) -> BuildResult:
        request.staging_root.joinpath("index.html").write_text(
            "<!doctype html><html><head></head><body>"
            '<main id="app-shell"></main></body></html>',
            encoding="utf-8",
        )
        return BuildResult(PurePosixPath("index.html"), ())


class _CreateProcessTreeProvider(ProviderStub):
    def create(self, starter: ProviderStarter, context: StarterContext):
        del starter, context
        marker_value = os.environ.get("MARIMO_STUDIO_PROVIDER_CREATE_MARKER")
        if not marker_value:
            raise RuntimeError("Create process fixture requires a marker")
        marker = Path(marker_value)
        marker.write_text(f"{os.getpid()}\n", encoding="utf-8")
        command = (
            "import os, pathlib, subprocess, sys, time; "
            "grandchild = subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(30)']); "
            f"stream = pathlib.Path({str(marker)!r}).open('a'); "
            "stream.write(f'{os.getpid()}\\n{grandchild.pid}\\n'); "
            "stream.flush(); os.fsync(stream.fileno()); stream.close(); "
            "time.sleep(30)"
        )
        subprocess.Popen([sys.executable, "-c", command])
        threading.Event().wait(30)
        raise AssertionError("Unreachable")


class _IgnoringCancellationProvider(ProviderStub):
    def _block(self, project: ViewProject) -> None:
        marker = project.options.get("marker")
        if not isinstance(marker, str):
            raise RuntimeError("Cancellation fixture requires a marker path")
        Path(marker).write_text("entered", encoding="utf-8")
        while True:
            time.sleep(60)

    def inspect(self, request: Any) -> ProjectInspection:
        self._block(request.project)
        raise AssertionError("Unreachable")

    def build(self, request: Any) -> BuildResult:
        self._block(request.project)
        raise AssertionError("Unreachable")


class _DelayedProvider(ProviderStub):
    def inspect(self, request: Any):
        threading.Event().wait(float(request.project.options["delay"]))
        request.runner.run(
            [
                sys.executable,
                "-c",
                f"import time; time.sleep({request.project.options['command']!r})",
            ],
            cwd=request.project.root,
            timeout=request.command_timeout,
        )
        return inspection()


class _CatalogProvider(ProviderStub):
    @staticmethod
    def _record(operation: str) -> None:
        marker = os.environ.get("MARIMO_STUDIO_PROVIDER_CATALOG_MARKER")
        if marker:
            with Path(marker).open("a", encoding="utf-8") as stream:
                stream.write(f"{operation}:{os.getpid()}\n")

    @staticmethod
    def _block(operation: str) -> None:
        if os.environ.get("MARIMO_STUDIO_PROVIDER_BLOCK") == operation:
            threading.Event().wait(30)

    def availability(self, project: ViewProject | None = None):
        self._record("availability")
        self._block("availability")
        return super().availability(project)

    def starters(self):
        self._record("starters")
        self._block("starters")
        return super().starters()

    def create(self, starter: ProviderStarter, context: StarterContext):
        self._record("create")
        self._block("create")
        return super().create(starter, context)


class _BlockingDescriptionProvider:
    def __init__(self) -> None:
        self._provider = ProviderStub(
            "test-process/blocking-description",
            "default",
        )

    @property
    def info(self) -> ProviderInfo:
        marker = os.environ.get("MARIMO_STUDIO_PROVIDER_DESCRIPTION_MARKER")
        if marker:
            Path(marker).write_text(str(os.getpid()), encoding="utf-8")
        threading.Event().wait(30)
        raise AssertionError("Unreachable")

    def availability(self, project: ViewProject | None = None):
        return self._provider.availability(project)

    def starters(self):
        return self._provider.starters()

    def create(self, starter: ProviderStarter, context: StarterContext):
        return self._provider.create(starter, context)

    def inspect(self, request: Any):
        return self._provider.inspect(request)

    def build(self, request: Any):
        return self._provider.build(request)


process_tree_provider = _ProcessTreeProvider("test-process/tree", "default")
build_tree_provider = _BuildProcessTreeProvider(
    "test-process/build-tree",
    "default",
)
runtime_provider = _RuntimeProvider("test-process/runtime", "default")
create_tree_provider = _CreateProcessTreeProvider(
    "test-process/create-tree",
    "default",
)
delayed_provider = _DelayedProvider("test-process/delayed", "default")
catalog_provider = _CatalogProvider("test-process/catalog", "default")
blocking_description_provider = _BlockingDescriptionProvider()
catalog_provider.plan = {
    PurePosixPath("index.html"): b"<!doctype html>\x00<html></html>"
}
ignoring_cancellation_provider = _IgnoringCancellationProvider(
    "test-isolated/ignoring",
    "default",
)


def _registry(
    name: str,
    provider_name: str,
    *,
    timeout: float = 10,
) -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderCandidate(
                registration=name,
                distribution="test-process",
                version="1.0.0",
                entry_point=EntryPoint(
                    name=name,
                    value=f"{__name__}:{provider_name}",
                    group="marimo_studio.view_provider",
                ),
            ),
        ),
        isolate_operations=True,
        extension_timeout=timeout,
    )


def _project(tmp_path: Path, provider: str, **options: JsonValue) -> ViewProject:
    root = tmp_path / "view"
    root.mkdir()
    manifest = root / "view.toml"
    manifest.write_text("schema = 1\n", encoding="utf-8")
    (root / "index.html").write_text("<main></main>", encoding="utf-8")
    return ViewProject("dashboard", root, manifest, provider, options)


def _external_build_studio(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[StudioWorkspace, Path]:
    import marimo_studio.view_providers._host as providers_module
    from marimo_studio._workspace import load_studio
    from marimo_studio._workspace.project_manifest import encode_view_manifest

    from ..app_helpers import configured

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    studio = configured(notebook_path)
    marker = tmp_path / "build-pids"
    project = studio.views["dashboard"]
    project.manifest.write_text(
        encode_view_manifest(
            "test-process/build-tree",
            {"marker": str(marker)},
        ),
        encoding="utf-8",
    )
    registry = _registry("build-tree", "build_tree_provider")
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)
    return load_studio(notebook_path), marker


def _wait_for_pids(marker: Path, count: int) -> tuple[int, ...]:
    deadline = time.monotonic() + _PROCESS_START_TIMEOUT
    while time.monotonic() < deadline:
        if marker.is_file():
            try:
                pids = tuple(
                    int(line)
                    for line in marker.read_text(encoding="utf-8").splitlines()
                )
            except ValueError:
                pids = ()
            if len(pids) == count:
                return pids
        threading.Event().wait(0.01)
    raise AssertionError("Provider process tree did not report every PID")


def _pid_is_live(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
        return f'"{pid}"' in result.stdout
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait_until_dead(pids: tuple[int, ...]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(_pid_is_live(pid) for pid in pids):
        threading.Event().wait(0.01)
    assert all(not _pid_is_live(pid) for pid in pids)


def _kill_survivors(pids: tuple[int, ...]) -> None:
    for pid in pids:
        if not _pid_is_live(pid):
            continue
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
        else:
            with suppress(ProcessLookupError):
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def _kill_reported_processes(marker: Path, pids: tuple[int, ...]) -> None:
    if not pids and marker.is_file():
        try:
            pids = tuple(
                int(line)
                for line in marker.read_text(encoding="utf-8").splitlines()
                if line
            )
        except (OSError, ValueError):
            pids = ()
    _kill_survivors(pids)


@pytest.mark.parametrize("finish", ("cancel", "timeout"))
def test_isolated_provider_owns_its_complete_command_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finish: str,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    registry = _registry("tree", "process_tree_provider")
    installed = registry.get("test-process/tree")
    marker = tmp_path / "pids"
    project = _project(tmp_path, installed.key, marker=str(marker))
    cancellation = ProviderCancellation()
    timeout = 0.25 if finish == "timeout" else 30.0
    request = inspection_request(
        project,
        cancellation=cancellation,
        command_timeout=timeout,
    )
    errors: list[BaseException] = []
    operation = threading.Thread(
        target=lambda: _capture_error(errors, installed.inspect, request)
    )
    pids: tuple[int, ...] = ()
    try:
        operation.start()
        pids = _wait_for_pids(marker, 3)
        if finish == "cancel":
            cancellation.cancel()
        operation.join(timeout=_PROCESS_START_TIMEOUT)

        assert not operation.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], ViewProjectError)
        expected = ("cancelled",) if finish == "cancel" else ("budget", "exceeded")
        assert any(marker in str(errors[0]).lower() for marker in expected)
        _wait_until_dead(pids)
    finally:
        _kill_survivors(pids)


def test_snapshot_request_cancellation_drains_the_complete_process_tree(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, marker = _external_build_studio(notebook_path, tmp_path, monkeypatch)
    pids: tuple[int, ...] = ()

    async def exercise() -> tuple[int, ...]:
        from marimo_studio._server.presentation.service import NotebookPresentation

        coordinator = DevelopmentCoordinator()
        presentation = NotebookPresentation(
            studio.notebook,
            development=coordinator,
        )
        snapshot = asyncio.create_task(presentation.snapshot_async("dashboard"))
        recorded = await asyncio.to_thread(_wait_for_pids, marker, 3)
        try:
            snapshot.cancel()
            await asyncio.gather(snapshot, return_exceptions=True)
            await asyncio.to_thread(_wait_until_dead, recorded)
            return recorded
        finally:
            presentation.close()
            await coordinator.close()

    try:
        pids = asyncio.run(exercise())
    finally:
        _kill_reported_processes(marker, pids)


def test_view_creation_http_cancellation_drains_provider_work_before_return(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import marimo_studio.view_providers._host as providers_module
    from marimo_studio._workspace.config import (
        canonical_view_root,
        load_studio_definition,
    )

    from ..app_helpers import configured

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    configured(notebook_path)
    marker = tmp_path / "create-pids"
    monkeypatch.setenv("MARIMO_STUDIO_PROVIDER_CREATE_MARKER", str(marker))
    registry = _registry("create-tree", "create_tree_provider")
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)
    pids: tuple[int, ...] = ()

    async def exercise() -> tuple[int, ...]:
        from starlette.authentication import AuthCredentials
        from starlette.requests import Request

        from marimo_studio._server.studio.routes import create_view_response

        body = json.dumps(
            {
                "name": "cancelled",
                "starter": "test-process/create-tree:default",
            }
        ).encode()
        sent = False

        async def receive() -> dict[str, object]:
            nonlocal sent
            if sent:
                await asyncio.Future()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/_marimo-studio/views",
                "raw_path": b"/_marimo-studio/views",
                "root_path": "",
                "query_string": b"",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"marimo-server-token", b"server-token"),
                ],
                "client": ("127.0.0.1", 50000),
                "server": ("127.0.0.1", 2718),
                "auth": AuthCredentials(["read", "edit"]),
            },
            receive,
        )
        operation = asyncio.create_task(
            create_view_response(
                request,
                load_studio_definition(notebook_path),
                "server-token",
            )
        )
        recorded = await asyncio.to_thread(_wait_for_pids, marker, 3)
        operation.cancel()
        results = await asyncio.gather(operation, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        await asyncio.to_thread(_wait_until_dead, recorded)
        assert not (canonical_view_root(notebook_path) / "cancelled").exists()
        return recorded

    try:
        pids = asyncio.run(exercise())
    finally:
        _kill_reported_processes(marker, pids)


def test_cli_sigint_drains_the_provider_process_tree(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio, marker = _external_build_studio(notebook_path, tmp_path, monkeypatch)
    script = (
        "import marimo_studio.view_providers._host as providers; "
        "from tests.providers.test_process_isolation import _registry; "
        "providers._REGISTRY = _registry('build-tree', 'build_tree_provider'); "
        "from marimo_studio._cli.main import cli; "
        f"cli.main(args=['validate', {str(studio.notebook)!r}, "
        "'--view', 'dashboard'])"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[2])
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    pids: tuple[int, ...] = ()
    try:
        pids = _wait_for_pids(marker, 3)
        os.kill(process.pid, signal.SIGINT)
        process.wait(timeout=5)
        _wait_until_dead(pids)
        assert process.returncode != 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        _kill_reported_processes(marker, pids)


@pytest.mark.parametrize("finish", ("cancel", "timeout"))
def test_external_provider_runtime_validation_owns_the_complete_runtime_tree(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finish: str,
) -> None:
    import marimo_studio.view_providers._host as providers_module
    from marimo_studio._validation.runtime_process import (
        check_runtime_studio_isolated,
    )
    from marimo_studio._views.build import build_view_project_sync
    from marimo_studio._views.revisions import capture_source_revisions
    from marimo_studio._workspace import load_studio
    from marimo_studio._workspace.project_manifest import encode_view_manifest

    from ..app_helpers import configured

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[2]))
    studio = configured(notebook_path)
    marker = tmp_path / "runtime-pids"
    child_code = (
        "import os, pathlib, subprocess, sys, time; "
        "grandchild = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(30)']); "
        f"stream = pathlib.Path({str(marker)!r}).open('a'); "
        "stream.write(f'{os.getpid()}\\n{grandchild.pid}\\n'); "
        "stream.flush(); os.fsync(stream.fileno()); stream.close(); "
        "time.sleep(30)"
    )
    runtime_cell = (
        "\n\n@app.cell\n"
        "def _():\n"
        "    import os as _os\n"
        "    import subprocess as _subprocess\n"
        "    import sys as _sys\n"
        "    import time as _time\n"
        "    from pathlib import Path as _Path\n"
        f"    _runtime_marker = _Path({str(marker)!r})\n"
        "    _runtime_marker.write_text(f'{_os.getpid()}\\n', "
        "encoding='utf-8')\n"
        f"    _subprocess.Popen([_sys.executable, '-c', {child_code!r}])\n"
        "    _time.sleep(30)\n"
        "    return\n"
    )
    source = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        source.replace(
            '\nif __name__ == "__main__":',
            runtime_cell + '\nif __name__ == "__main__":',
        ),
        encoding="utf-8",
    )
    project = studio.views["dashboard"]
    project.manifest.write_text(
        encode_view_manifest("test-process/runtime"),
        encoding="utf-8",
    )
    registry = _registry("runtime", "runtime_provider")
    monkeypatch.setattr(providers_module, "_REGISTRY", registry)
    studio = load_studio(notebook_path)
    with build_view_project_sync(studio.views["dashboard"]):
        pass
    expected = capture_source_revisions(studio, ("dashboard",))
    pids: tuple[int, ...] = ()

    async def exercise() -> tuple[int, ...]:
        timeout = 3.0 if finish == "timeout" else 30.0
        validation = asyncio.create_task(
            check_runtime_studio_isolated(
                studio,
                view_name="dashboard",
                expected_revisions=expected,
                timeout=timeout,
            )
        )
        deadline = asyncio.get_running_loop().time() + 8
        while not marker.is_file() and not validation.done():
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("Runtime process tree did not start")
            await asyncio.sleep(0.01)
        if validation.done():
            checks = await validation
            raise AssertionError(
                "Runtime validation finished before the process tree started: "
                + "; ".join(check.message for check in checks)
            )
        recorded = await asyncio.to_thread(_wait_for_pids, marker, 3)
        if finish == "cancel":
            validation.cancel()
            results = await asyncio.gather(validation, return_exceptions=True)
            assert isinstance(results[0], asyncio.CancelledError)
        else:
            checks = await validation
            assert any(check.code == "runtime-timeout" for check in checks)
        await asyncio.to_thread(_wait_until_dead, recorded)
        return recorded

    try:
        pids = asyncio.run(exercise())
    finally:
        _kill_reported_processes(marker, pids)


def _capture_error(
    errors: list[BaseException],
    operation: Any,
    request: object,
) -> None:
    try:
        operation(request)
    except BaseException as error:
        errors.append(error)
