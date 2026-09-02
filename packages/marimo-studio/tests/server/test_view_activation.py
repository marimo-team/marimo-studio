from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from marimo_studio._browser_client.protocol import ViewShowRequest
from marimo_studio._server.agent.activation import ActivationAckOutcome
from marimo_studio._server.development.client_events import WorkspaceClientEventProducer
from marimo_studio._server.notebook_scope import NotebookScope
from marimo_studio._server.ports import SessionState
from marimo_studio._server.presentation.activation import (
    BrowserViewTarget,
    SessionViewTarget,
    activate_studio_view,
)
from marimo_studio._server.records import ServerContext
from marimo_studio._workspace.ownership import AbsentViewOwner, PresentViewOwner
from marimo_studio.errors import (
    AgentRequestError,
    CapabilityInputError,
    ViewNotFoundError,
)

from ..app_helpers import configured
from ..client_test_support import bind_native_session


def test_activation_request_round_trips_its_versioned_record() -> None:
    request = ViewShowRequest(
        "dashboard",
        browser_client="browser-client-1234",
        owner=PresentViewOwner("a" * 64, "b" * 64),
    )
    absent = ViewShowRequest("report", owner=AbsentViewOwner("a" * 64))

    assert ViewShowRequest.from_dict("dashboard", request.to_dict()) == request
    assert ViewShowRequest.from_dict(
        "dashboard",
        ViewShowRequest("dashboard").to_dict(),
    ) == ViewShowRequest("dashboard")
    assert ViewShowRequest.from_dict("report", absent.to_dict()) == absent
    for payload in (
        {**request.to_dict(), "schema": True},
        {**request.to_dict(), "unexpected": True},
        {
            key: value
            for key, value in request.to_dict().items()
            if key != "view_generation"
        },
        {
            **ViewShowRequest("dashboard").to_dict(),
            "catalog_generation": "a" * 64,
        },
    ):
        with pytest.raises(CapabilityInputError) as raised:
            ViewShowRequest.from_dict("dashboard", payload)
        assert raised.value.field in {
            "request",
            "catalog_generation",
            "view_generation",
        }


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


def test_external_activation_targets_the_selected_or_only_browser(
    notebook_path,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    async def exercise():
        assert await notebook_scope.clients.connect_stream("browser-client-1234", 1)
        await bind_native_session(
            notebook_scope.clients,
            "s_123456",
            "browser-client-1234",
        )
        return (
            await _activate_connected(
                notebook_scope,
                studio,
                BrowserViewTarget("browser-client-1234"),
            ),
            await _activate_connected(
                notebook_scope,
                studio,
                BrowserViewTarget(None),
            ),
        )

    selected, implicit = asyncio.run(exercise())

    assert selected.view == "dashboard"
    assert selected.client_id == "browser-client-1234"
    assert selected.session_id == "s_123456"
    assert implicit.client_id == "browser-client-1234"


def test_external_activation_rejects_ambiguous_browsers(notebook_path) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)

    async def exercise() -> None:
        for index in range(2):
            client_id = f"browser-client-{index}"
            assert await notebook_scope.clients.connect_stream(client_id, index + 1)
            await bind_native_session(
                notebook_scope.clients,
                f"s_{index}",
                client_id,
            )
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
        assert await notebook_scope.clients.connect_stream("browser-client-1234", 1)
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


def test_session_activation_requires_its_studio_host(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    notebook_scope = NotebookScope.create(studio.notebook)
    monkeypatch.setattr(
        "marimo_studio._server.presentation.activation._CLIENT_CONNECT_TIMEOUT",
        0.02,
    )

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
            1,
            None,
        )
        await pre_host.connect()
        await bind_native_session(notebook_scope.clients, "s_123456", client_id)
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
            2,
            "dashboard",
        )
        await workspace.connect()
        replayed = await next_activation(workspace)
        assert replayed == delivered
        assert (
            await notebook_scope.agents.acknowledge_activation(
                client_id,
                replayed[0],
                replayed[1],
            )
            is ActivationAckOutcome.APPLIED
        )
        result = await operation
        await workspace.close()
        await notebook_scope.close()
        return result

    result = asyncio.run(exercise())

    assert result.view == "dashboard"
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
