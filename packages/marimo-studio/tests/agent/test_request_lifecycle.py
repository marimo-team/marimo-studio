from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.authentication import AuthCredentials
from starlette.requests import Request
from starlette.types import Message, Scope

from marimo_studio._server.agent import api as agent_api
from marimo_studio._server.agent import browser as browser_agent
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._workspace.models import StudioWorkspace

from ..app_helpers import configured
from ..client_test_support import bind_native_session


def _native_context(studio: StudioWorkspace) -> Any:
    editor_session = SimpleNamespace(
        initialization_id="notebook.py",
        app_file_manager=SimpleNamespace(path=studio.notebook),
    )
    return SimpleNamespace(
        server_token="server-token",
        file_key="notebook.py",
        notebook=studio.notebook,
        _session_manager=SimpleNamespace(
            get_session=lambda session_id: (
                editor_session if str(session_id) == "s_123456" else None
            )
        ),
    )


def test_observation_disconnect_clears_the_browser_operation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    context = _native_context(studio)

    async def project_runtime(*_args: object) -> object:
        return SimpleNamespace(instance="runtime-instance")

    sessions = cast(
        SessionState,
        SimpleNamespace(
            exists=lambda *_args: True,
            is_session_id=lambda value: isinstance(value, str),
        ),
    )
    runtimes = cast(
        RuntimeRegistry,
        SimpleNamespace(ids=("server",), project=project_runtime),
    )

    async def exercise() -> tuple[int, tuple[object, ...]]:
        client_id = "browser-client-1234"
        assert await notebook_scope.clients.connect_stream(client_id, 1, "dashboard")
        await bind_native_session(notebook_scope.clients, "s_123456", client_id)
        target = await notebook_scope.clients.select_target(client_id=client_id)
        revision = (
            await notebook_scope.presentation.snapshot_async("dashboard")
        ).revision
        requested = asyncio.Event()
        request_observation = notebook_scope.agents.request_observation

        async def capture_observation(*args: Any, **kwargs: Any):
            result = await request_observation(*args, **kwargs)
            requested.set()
            return result

        cast(Any, notebook_scope.agents).request_observation = capture_observation
        request, messages = _request(
            "/_marimo-studio/observations",
            {
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": revision},
                "runtime": "server",
                "timeout": 300,
                "browserClient": client_id,
            },
        )
        operation = asyncio.create_task(
            browser_agent.browser_observations_response(
                request,
                context,
                studio,
                notebook_scope,
                sessions,
                runtimes,
            )
        )
        await asyncio.wait_for(requested.wait(), timeout=1)

        await messages.put({"type": "http.disconnect"})
        response = await asyncio.wait_for(operation, timeout=1)
        settled = await notebook_scope.agents.pending_operations(
            target,
            None,
            None,
        )
        return response.status_code, settled.observations

    status_code, pending = asyncio.run(exercise())

    assert status_code == 499
    assert pending == ()


def test_validation_disconnect_cancels_runtime_validation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    context: Any = SimpleNamespace(server_token="server-token")
    started: asyncio.Event
    cancelled: asyncio.Event

    async def runtime(
        _studio: StudioWorkspace,
        **_kwargs: object,
    ) -> tuple[()]:
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
        return ()

    monkeypatch.setattr(agent_api, "check_runtime_studio_isolated", runtime)

    async def exercise() -> tuple[int, bool]:
        nonlocal started, cancelled
        started = asyncio.Event()
        cancelled = asyncio.Event()
        request, messages = _request(
            "/_marimo-studio/validate",
            {
                "schema": 1,
                "view": "dashboard",
                "browser_timeout": 10,
                "require_browser": False,
            },
        )
        operation = asyncio.create_task(
            agent_api.validate_views_response(
                request,
                context,
                studio,
                notebook_scope,
                cast(
                    SessionState,
                    SimpleNamespace(
                        exists=lambda *_args: True,
                        is_session_id=lambda value: isinstance(value, str),
                    ),
                ),
                cast(RuntimeRegistry, SimpleNamespace()),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await messages.put({"type": "http.disconnect"})
        response = await asyncio.wait_for(operation, timeout=1)
        return response.status_code, cancelled.is_set()

    status_code, runtime_cancelled = asyncio.run(exercise())

    assert status_code == 499
    assert runtime_cancelled


def test_already_disconnected_observation_skips_source_capture(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    context = _native_context(studio)
    snapshots = 0

    async def snapshot(_view: str) -> object:
        nonlocal snapshots
        snapshots += 1
        raise AssertionError("A disconnected request captured Studio sources")

    monkeypatch.setattr(notebook_scope.presentation, "snapshot_async", snapshot)

    async def exercise() -> int:
        client_id = "browser-client-1234"
        assert await notebook_scope.clients.connect_stream(client_id, 1)
        await bind_native_session(notebook_scope.clients, "s_123456", client_id)
        request, messages = _request(
            "/_marimo-studio/observations",
            {
                "schema": 1,
                "views": ["dashboard"],
                "revisions": {"dashboard": "revision-1"},
                "runtime": "server",
                "timeout": 0,
                "browserClient": client_id,
            },
        )
        messages.put_nowait({"type": "http.disconnect"})
        response = await browser_agent.browser_observations_response(
            request,
            context,
            studio,
            notebook_scope,
            cast(
                SessionState,
                SimpleNamespace(
                    exists=lambda *_args: True,
                    is_session_id=lambda value: isinstance(value, str),
                ),
            ),
            cast(RuntimeRegistry, SimpleNamespace(ids=("server",))),
        )
        return response.status_code

    assert asyncio.run(exercise()) == 499
    assert snapshots == 0


def test_observation_view_limit_applies_after_default_expansion(
    notebook_path: Path,
) -> None:
    configured_studio = configured(notebook_path)
    studio = cast(
        StudioWorkspace,
        SimpleNamespace(
            views={f"view-{index}": object() for index in range(101)},
            default_runtime="server",
        ),
    )
    notebook_scope = NotebookScope.create(configured_studio.notebook)
    context: Any = SimpleNamespace(server_token="server-token")
    request, _messages = _request(
        "/_marimo-studio/observations",
        {
            "schema": 1,
            "views": [],
            "revisions": {},
            "runtime": "server",
            "timeout": 10,
            "browserClient": None,
        },
    )

    response = asyncio.run(
        browser_agent.browser_observations_response(
            request,
            context,
            studio,
            notebook_scope,
            cast(
                SessionState,
                SimpleNamespace(
                    exists=lambda *_args: True,
                    is_session_id=lambda value: isinstance(value, str),
                ),
            ),
            cast(RuntimeRegistry, SimpleNamespace(ids=("server",))),
        )
    )

    assert response.status_code == 400
    assert json.loads(bytes(response.body))["error"] == "too-many-browser-views"


def test_show_disconnect_clears_the_browser_operation(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    context = _native_context(studio)

    async def exercise() -> tuple[int, object | None]:
        client_id = "browser-client-1234"
        assert await notebook_scope.clients.connect_stream(client_id, 1)
        await bind_native_session(notebook_scope.clients, "s_123456", client_id)
        target = await notebook_scope.clients.select_target(client_id=client_id)
        requested = asyncio.Event()
        activate = notebook_scope.agents.activate

        async def capture_activation(*args: Any, **kwargs: Any):
            result = await activate(*args, **kwargs)
            requested.set()
            return result

        cast(Any, notebook_scope.agents).activate = capture_activation
        request, messages = _request(
            "/_marimo-studio/views/dashboard/show",
            {"schema": 1, "browser_client": None},
            method="PATCH",
            session_id="s_123456",
        )
        operation = asyncio.create_task(
            agent_api.show_view_response(
                request,
                context,
                studio,
                "dashboard",
                notebook_scope,
                cast(
                    SessionState,
                    SimpleNamespace(
                        exists=lambda *_args: True,
                        is_session_id=lambda value: isinstance(value, str),
                    ),
                ),
            )
        )
        await asyncio.wait_for(requested.wait(), timeout=1)

        await messages.put({"type": "http.disconnect"})
        response = await asyncio.wait_for(operation, timeout=1)
        settled = await notebook_scope.agents.pending_operations(
            target,
            None,
            None,
        )
        return response.status_code, settled.activation

    status_code, pending = asyncio.run(exercise())

    assert status_code == 499
    assert pending is None


@pytest.mark.parametrize(
    ("stale_owner", "error_code"),
    (
        ("catalog", "workspace-generation-conflict"),
        ("view", "view-generation-conflict"),
        ("absent-view", "view-generation-conflict"),
    ),
)
def test_show_rejects_stale_view_ownership_before_activation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_owner: str,
    error_code: str,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    context = _native_context(studio)
    activated = False

    async def activate(*_args: object, **_kwargs: object) -> object:
        nonlocal activated
        activated = True
        raise AssertionError("stale view reached browser activation")

    monkeypatch.setattr(agent_api, "activate_studio_view", activate)
    request, _messages = _request(
        "/_marimo-studio/views/dashboard/show",
        {
            "schema": 1,
            "browser_client": None,
            "catalog_generation": (
                "0" * 64 if stale_owner == "catalog" else studio.catalog_generation
            ),
            "view_generation": (
                None
                if stale_owner == "absent-view"
                else (
                    "0" * 64
                    if stale_owner == "view"
                    else studio.view_generations["dashboard"]
                )
            ),
        },
        method="PATCH",
    )

    response = asyncio.run(
        agent_api.show_view_response(
            request,
            context,
            studio,
            "dashboard",
            notebook_scope,
            cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
        )
    )

    assert response.status_code == 409
    assert json.loads(bytes(response.body))["error"] == error_code
    assert not activated


def test_show_rejects_a_replacement_before_browser_acknowledgement(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    context = _native_context(studio)

    async def exercise() -> tuple[int, int, str, str | None]:
        client_id = "browser-client-1234"
        assert await notebook_scope.clients.connect_stream(client_id, 1, "executive")
        await bind_native_session(notebook_scope.clients, "s_123456", client_id)
        requested = asyncio.Event()
        activate = notebook_scope.agents.activate
        activation = None

        async def capture_activation(*args: Any, **kwargs: Any):
            nonlocal activation
            activation = await activate(*args, **kwargs)
            requested.set()
            return activation

        cast(Any, notebook_scope.agents).activate = capture_activation
        show_request, _show_messages = _request(
            "/_marimo-studio/views/dashboard/show",
            {
                "schema": 1,
                "browser_client": None,
                "catalog_generation": studio.catalog_generation,
                "view_generation": studio.view_generations["dashboard"],
            },
            method="PATCH",
            session_id="s_123456",
        )
        showing = asyncio.create_task(
            agent_api.show_view_response(
                show_request,
                context,
                studio,
                "dashboard",
                notebook_scope,
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
            )
        )
        await asyncio.wait_for(requested.wait(), timeout=1)
        assert activation is not None

        root = studio.views["dashboard"].root
        retired = root.with_name("retired-dashboard")
        root.rename(retired)
        shutil.copytree(retired, root)

        ack_request, _ack_messages = _request(
            f"/_marimo-studio/activations/{activation.generation}/ack",
            {
                "schema": 1,
                "clientId": client_id,
                "view": "dashboard",
                "catalogGeneration": studio.catalog_generation,
                "viewGeneration": studio.view_generations["dashboard"],
            },
        )
        acknowledged = await agent_api.activation_ack_response(
            ack_request,
            context,
            studio,
            notebook_scope,
            activation.generation,
        )
        shown = await asyncio.wait_for(showing, timeout=1)
        target = await notebook_scope.clients.target_for_client(client_id)
        return (
            acknowledged.status_code,
            shown.status_code,
            json.loads(bytes(shown.body))["error"],
            target.active_view if target is not None else None,
        )

    ack_status, show_status, show_error, active_view = asyncio.run(exercise())

    assert ack_status == 409
    assert show_status == 409
    assert show_error == "view-generation-conflict"
    assert active_view == "executive"


@pytest.mark.native_process
def test_validation_disconnect_drains_the_provider_build_process_tree(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ..providers.test_process_isolation import (
        _external_build_studio,
        _kill_survivors,
        _wait_for_pids,
        _wait_until_dead,
    )

    studio, marker = _external_build_studio(notebook_path, tmp_path, monkeypatch)
    notebook_scope = NotebookScope.create(studio.notebook)
    context: Any = SimpleNamespace(server_token="server-token")
    pids: tuple[int, ...] = ()

    async def exercise() -> tuple[int, tuple[int, ...]]:
        request, messages = _request(
            "/_marimo-studio/validate",
            {
                "schema": 1,
                "view": "dashboard",
                "require_browser": False,
            },
        )
        operation = asyncio.create_task(
            agent_api.validate_views_response(
                request,
                context,
                studio,
                notebook_scope,
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
                cast(RuntimeRegistry, SimpleNamespace()),
            )
        )
        recorded = await asyncio.to_thread(_wait_for_pids, marker, 3)
        await messages.put({"type": "http.disconnect"})
        response = await asyncio.wait_for(operation, timeout=5)
        await asyncio.to_thread(_wait_until_dead, recorded)
        return response.status_code, recorded

    try:
        status_code, pids = asyncio.run(exercise())
        assert status_code == 499
    finally:
        asyncio.run(notebook_scope.close())
        if not pids and marker.is_file():
            pids = tuple(
                int(line)
                for line in marker.read_text(encoding="utf-8").splitlines()
                if line
            )
        _kill_survivors(pids)


def _request(
    path: str,
    payload: dict[str, object],
    *,
    method: str = "POST",
    session_id: str | None = None,
) -> tuple[Request, asyncio.Queue[Message]]:
    body = json.dumps(payload).encode()
    messages: asyncio.Queue[Message] = asyncio.Queue()
    messages.put_nowait({"type": "http.request", "body": body, "more_body": False})
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"marimo-server-token", b"server-token"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 2718),
        "auth": AuthCredentials(["read", "edit"]),
    }
    if session_id is not None:
        scope["headers"].append((b"marimo-session-id", session_id.encode()))

    async def receive() -> Message:
        return await messages.get()

    return Request(scope, receive), messages
