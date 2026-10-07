from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import marimo_studio.agent as agent
import marimo_studio.authoring as authoring
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._workspace import load_studio
from marimo_studio.errors import ProtocolError, ViewGenerationConflictError

from ..helpers import write_marimohub_context


def test_saved_view_resolves_a_plain_url_with_connection_routing(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = authoring.open_workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))
    calls = []

    async def request(connection, path, *, query):
        calls.append((connection, path, dict(query)))
        return (
            "../../../dashboard/?file=analysis.py&runtime=wasm&marimo_studio_unframed=1"
        )

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    # The server URL can carry a proxy prefix that the Studio server never sees.
    url = asyncio.run(
        view.preview_url(
            runtime="wasm",
            server="https://workbench.example/s/f3a9/p/77c1/?file=analysis.py",
            access_token="secret",
            exact=True,
        )
    )
    assert url == (
        "https://workbench.example/s/f3a9/p/77c1/dashboard/"
        "?file=analysis.py&runtime=wasm&marimo_studio_unframed=1"
    )
    connection, path, query = calls[0]
    assert connection.auth_token == "secret"
    assert connection.routing_query == (("file", "analysis.py"),)
    assert connection.browser_client == ""
    assert path == "/_marimo-studio/views/dashboard/preview"
    assert query == {
        "runtime": "wasm",
        "exact": "1",
        "catalog_generation": view.catalog_generation,
        "view_generation": view.generation,
    }


def test_saved_view_preview_names_the_studio_tab_it_follows(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = authoring.open_workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))
    queries = []

    async def request(_connection, _path, *, query):
        queries.append(dict(query))
        return "../../../dashboard/?runtime=zero-python&marimo_studio_unframed=1"

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    asyncio.run(
        view.preview_url(
            runtime="zero-python",
            server="http://localhost:2718",
            browser_client="browser-client-1234",
        )
    )
    assert queries[0]["marimo_studio_client"] == "browser-client-1234"


def test_current_view_infers_its_attached_server(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    connection = StudioServerConnection("http://localhost:2718", session_id="s_123456")
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: connection,
        ),
    )

    async def request(actual, path, *, query):
        assert actual is connection
        assert dict(query)["runtime"] == "server"
        return "../../../dashboard/?runtime=server&marimo_studio_unframed=1"

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    url = asyncio.run(
        agent.current_workspace().view("dashboard").preview_url(runtime="server")
    )
    assert url.startswith("http://localhost:2718/dashboard/")


@pytest.mark.parametrize(
    ("public_url", "server", "expected"),
    [
        (
            "https://hub.example/proxy/token/",
            "http://127.0.0.1:2718/proxy/token",
            "https://hub.example/proxy/token/",
        ),
        (
            "https://hub.example/marimohub/proxy/token",
            "http://localhost:2718/marimohub/proxy/token",
            "https://hub.example/marimohub/proxy/token/",
        ),
        (
            "https://sbx-1.sandbox.example/",
            "http://127.0.0.1:2718",
            "https://sbx-1.sandbox.example/",
        ),
        (
            "https://hub.example/proxy/token/",
            "http://127.0.0.1:2719/other",
            "http://127.0.0.1:2719/other/",
        ),
        (
            "https://hub.example/proxy/token/?access_token=secret",
            "http://127.0.0.1:2718/proxy/token",
            "http://127.0.0.1:2718/proxy/token/",
        ),
    ],
)
def test_current_view_preview_uses_the_marimohub_public_address(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    public_url: str,
    server: str,
    expected: str,
) -> None:
    write_marimohub_context(tmp_path, monkeypatch, public_url=public_url)
    workspace = authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    connection = StudioServerConnection(server, session_id="s_123456")
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: connection,
        ),
    )

    async def request(_connection, _path, *, query):
        return "../../../dashboard/?runtime=server&marimo_studio_unframed=1"

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    url = asyncio.run(
        agent.current_workspace().view("dashboard").preview_url(runtime="server")
    )
    assert url == f"{expected}dashboard/?runtime=server&marimo_studio_unframed=1"


def test_explicit_server_preview_keeps_its_address_in_a_hub_session(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_marimohub_context(
        tmp_path,
        monkeypatch,
        public_url="https://sbx-1.sandbox.example/",
        exposure_mode="subdomain",
    )
    view = asyncio.run(authoring.open_workspace(notebook_path).create_view("dashboard"))

    async def request(_connection, _path, *, query):
        return "../../../dashboard/?runtime=server&marimo_studio_unframed=1"

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    url = asyncio.run(
        view.preview_url(runtime="server", server="http://127.0.0.1:2718")
    )
    assert url == (
        "http://127.0.0.1:2718/dashboard/?runtime=server&marimo_studio_unframed=1"
    )


@pytest.mark.parametrize("when", ["before-request", "during-request"])
def test_preview_rejects_a_replaced_view_handle(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    workspace = authoring.open_workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))
    root = load_studio(notebook_path).views["dashboard"].root
    requested = False

    def replace() -> None:
        retired = root.with_name("retired-dashboard")
        root.rename(retired)
        shutil.copytree(retired, root)

    async def request(*_args, **_kwargs):
        nonlocal requested
        requested = True
        replace()
        return "../../../dashboard/?runtime=wasm&marimo_studio_unframed=1"

    if when == "before-request":
        replace()
    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    with pytest.raises(ViewGenerationConflictError):
        asyncio.run(view.preview_url(runtime="wasm", server="http://localhost:2718"))
    assert requested == (when == "during-request")


@pytest.mark.parametrize(
    "target",
    [
        "https://elsewhere.example/dashboard/",
        "//elsewhere.example/dashboard/",
        "/dashboard/",
        "../../../../dashboard/",
        "../../../dashboard/\nmalformed",
        # Browsers normalize these segments to `..` and leave the mount.
        "..\\..\\..\\..\\dashboard/",
        "../../../%2e%2e/dashboard/",
    ],
)
def test_preview_rejects_foreign_or_malformed_server_targets(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    workspace = authoring.open_workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))

    async def request(*_args, **_kwargs):
        return target

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    with pytest.raises(ProtocolError, match="invalid preview URL"):
        asyncio.run(
            view.preview_url(runtime="wasm", server="http://localhost:2718/base")
        )


def test_saved_view_needs_an_explicit_server(notebook_path: Path) -> None:
    workspace = authoring.open_workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))
    with pytest.raises(ProtocolError, match="Provide server"):
        asyncio.run(view.preview_url(runtime="wasm"))
    with pytest.raises(ValueError, match="require server"):
        asyncio.run(view.preview_url(runtime="wasm", access_token="secret"))
    with pytest.raises(ValueError, match="require server"):
        asyncio.run(view.preview_url(runtime="zero-python", browser_client="c" * 24))


def test_fresh_view_captures_its_owner_before_contacting_the_server(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = authoring.open_workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    fresh = authoring.open_workspace(notebook_path).view("dashboard")
    studio = load_studio(notebook_path)
    root = studio.views["dashboard"].root

    async def request(_connection, _path, *, query):
        observed = dict(query)
        assert observed["catalog_generation"] == studio.catalog_generation
        assert observed["view_generation"] == studio.view_generations["dashboard"]
        retired = root.with_name("retired-dashboard")
        root.rename(retired)
        shutil.copytree(retired, root)
        return "../../../dashboard/?runtime=wasm&marimo_studio_unframed=1"

    monkeypatch.setattr("marimo_studio._authoring.preview.request_text", request)
    with pytest.raises(ViewGenerationConflictError):
        asyncio.run(fresh.preview_url(runtime="wasm", server="http://localhost:2718"))
