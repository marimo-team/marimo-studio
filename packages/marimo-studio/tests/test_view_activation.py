from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from marimo_studio._capabilities import ServerContext, SessionState
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.view_activation import (
    BrowserViewTarget,
    SessionViewTarget,
    activate_studio_view,
)
from marimo_studio._server.workspace_client_events import WorkspaceClientEventProducer
from marimo_studio.activation import ViewActivationRequest
from marimo_studio.errors import (
    AgentRequestError,
    CapabilityInputError,
    ViewNotFoundError,
)

from .app_helpers import configured


def test_activation_request_round_trips_its_versioned_record() -> None:
    request = ViewActivationRequest(
        "dashboard",
        browser_client="browser-client-1234",
    )

    assert ViewActivationRequest.from_dict("dashboard", request.to_dict()) == request
    for payload in (
        {},
        {**request.to_dict(), "schema": True},
        {**request.to_dict(), "unexpected": True},
    ):
        with pytest.raises(CapabilityInputError) as raised:
            ViewActivationRequest.from_dict("dashboard", payload)
        assert raised.value.field == "request"


async def _activate_connected(
    notebook_scope: NotebookScope,
    studio,
    target: BrowserViewTarget,
):
    operation = asyncio.create_task(
        activate_studio_view(
            cast(ServerContext, SimpleNamespace()),
            studio,
            notebook_scope,
            cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
            "dashboard",
            target,
        )
    )
    browser = await notebook_scope.clients.select_target(client_id=target.client_id)
    for _attempt in range(100):
        pending = await notebook_scope.agents.pending_operations(browser, None, None)
        if pending.activation is not None:
            await notebook_scope.agents.acknowledge_activation(
                browser.client_id,
                pending.activation.generation,
                "dashboard",
            )
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("view activation was not requested")
    return await operation


def test_external_activation_targets_the_selected_browser(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    async def exercise():
        await notebook_scope.clients.connect("browser-client-1234")
        await notebook_scope.clients.bind_session(
            "s_123456",
            "browser-client-1234",
        )
        return await _activate_connected(
            notebook_scope,
            studio,
            BrowserViewTarget("browser-client-1234"),
        )

    result = asyncio.run(exercise())

    assert result.state == "active"
    assert result.client_id == "browser-client-1234"
    assert result.session_id == "s_123456"


def test_external_activation_selects_the_only_browser(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    async def exercise():
        await notebook_scope.clients.connect("browser-client-1234")
        await notebook_scope.clients.bind_session(
            "s_123456",
            "browser-client-1234",
        )
        return await _activate_connected(
            notebook_scope,
            studio,
            BrowserViewTarget(None),
        )

    result = asyncio.run(exercise())

    assert result.client_id == "browser-client-1234"


def test_external_activation_rejects_ambiguous_browsers(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    async def exercise() -> None:
        for index in range(2):
            client_id = f"browser-client-{index}"
            await notebook_scope.clients.connect(client_id)
            await notebook_scope.clients.bind_session(f"s_{index}", client_id)
        with pytest.raises(AgentRequestError) as raised:
            await activate_studio_view(
                cast(ServerContext, SimpleNamespace()),
                studio,
                notebook_scope,
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
                "dashboard",
                BrowserViewTarget(None),
            )
        assert raised.value.code == "browser-client-ambiguous"

    asyncio.run(exercise())


def test_external_activation_requires_a_bound_session(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    async def exercise() -> None:
        await notebook_scope.clients.connect("browser-client-1234")
        with pytest.raises(AgentRequestError) as raised:
            await activate_studio_view(
                cast(ServerContext, SimpleNamespace()),
                studio,
                notebook_scope,
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
                "dashboard",
                BrowserViewTarget("browser-client-1234"),
            )
        assert raised.value.code == "browser-session-unavailable"

    asyncio.run(exercise())


def test_session_activation_requires_its_studio_host(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    with pytest.raises(AgentRequestError) as raised:
        asyncio.run(
            activate_studio_view(
                cast(ServerContext, SimpleNamespace()),
                studio,
                notebook_scope,
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
                "dashboard",
                SessionViewTarget("s_123456"),
            )
        )

    assert raised.value.code == "browser-client-unavailable"


def test_first_view_activation_replays_across_host_promotion(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    client_id = "browser-client-1234"

    async def next_activation(
        producer: WorkspaceClientEventProducer,
    ) -> tuple[int, str]:
        for _attempt in range(100):
            events = await producer.poll()
            activation = next(
                (event for event in events if event.kind == "activate"), None
            )
            if activation is not None:
                generation = activation.payload["generation"]
                view = activation.payload["view"]
                assert isinstance(generation, int) and not isinstance(generation, bool)
                assert isinstance(view, str)
                return generation, view
            await asyncio.sleep(0.01)
        raise AssertionError("view activation was not delivered")

    async def exercise():
        pre_host = WorkspaceClientEventProducer(
            notebook_scope.clients,
            notebook_scope.agents,
            client_id,
            None,
        )
        await pre_host.connect()
        await notebook_scope.clients.bind_session("s_123456", client_id)
        operation = asyncio.create_task(
            activate_studio_view(
                cast(ServerContext, SimpleNamespace()),
                studio,
                notebook_scope,
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
                "dashboard",
                SessionViewTarget("s_123456"),
            )
        )
        delivered = await next_activation(pre_host)
        await pre_host.close()

        workspace = WorkspaceClientEventProducer(
            notebook_scope.clients,
            notebook_scope.agents,
            client_id,
            "dashboard",
        )
        await workspace.connect()
        replayed = await next_activation(workspace)
        assert replayed == delivered
        assert await notebook_scope.agents.acknowledge_activation(
            client_id,
            replayed[0],
            replayed[1],
        )
        result = await operation
        await workspace.close()
        await notebook_scope.close()
        return result

    result = asyncio.run(exercise())

    assert result.state == "active"
    assert result.client_id == client_id


def test_activation_reports_unknown_views(notebook_path) -> None:
    studio = configured(notebook_path)

    with pytest.raises(ViewNotFoundError) as raised:
        asyncio.run(
            activate_studio_view(
                cast(ServerContext, SimpleNamespace()),
                studio,
                NotebookScope.create(studio.notebook),
                cast(SessionState, SimpleNamespace(exists=lambda *_args: True)),
                "missing",
                BrowserViewTarget(None),
            )
        )

    assert raised.value.code == "view-not-found"
    assert raised.value.diagnostic_details()["available_views"] == list(studio.views)
