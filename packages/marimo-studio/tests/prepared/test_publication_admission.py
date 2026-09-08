from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlencode

import pytest
from marimo_export import PreparedExport
from marimo_export.publication import PreparedPublicationCandidate
from starlette.requests import Request

from marimo_studio._prepared.state_space import load_state_space_source
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.prepared_view_models import PreparedViewMetadata
from marimo_studio._server.prepared_views import (
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation.service import NotebookPresentation
from marimo_studio._server.zero_python_api import zero_python_response
from marimo_studio.errors import PublicationError

from ..client_test_support import bind_native_session
from ..delivery.export_test_support import configure_export_view


class _Prepared:
    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.closed = False
        self.plan = SimpleNamespace(document_sha256="4" * 64)

    def manifest(
        self,
        export_url: str,
        *,
        state: str | Mapping[str, object] | None = None,
        refresh_interval_ms: int | None = None,
    ) -> dict[str, object]:
        return {
            "schema": "marimo-export.prepared.v1",
            "instance": self.identity,
            "export_url": export_url,
            "inputs": {},
            "state_fingerprint": "5" * 64,
        }

    def close(self) -> None:
        self.closed = True


def test_state_space_admission_rejects_candidate_before_replacing_current(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view_root = configure_export_view(notebook_path)
    source = load_state_space_source(view_root)
    request = PreparedViewRequest(
        snapshot=NotebookPresentation(notebook_path).snapshot("dashboard"),
        state_space_source=source,
        server="http://localhost:2718",
        server_token="test",
        session_id="editor",
        binding_id="editor",
    )
    first, rejected = _Prepared("1" * 64), _Prepared("2" * 64)
    candidates = iter((first, rejected))
    metadata = PreparedViewMetadata(
        request=request,
        projections={"cells": {}, "outputs": {}, "values": {}},
        selected_inputs=None,
        plan_digest="3" * 64,
    )

    def prepare(*_args: object) -> PreparedPublicationCandidate[PreparedViewMetadata]:
        return PreparedPublicationCandidate(
            cast(PreparedExport, next(candidates)), metadata
        )

    monkeypatch.setattr(PreparedViewRegistry, "_prepare", prepare)
    registry = PreparedViewRegistry(notebook_path)
    clients = StudioClientRegistry()

    async def scenario() -> None:
        try:
            await clients.connect_stream("browser-client-1234", 1, "dashboard")
            await bind_native_session(clients, "editor", "browser-client-1234")
            current = await registry.prepare(request)
            source.path.write_text("schema: invalid\n", encoding="utf-8")
            with pytest.raises(PublicationError):
                await registry.prepare(request)
            assert rejected.closed
            assert not first.closed
            response = await zero_python_response(
                Request(
                    {
                        "type": "http",
                        "method": "GET",
                        "scheme": "http",
                        "server": ("testserver", 80),
                        "headers": [],
                        "path": "/_marimo-studio/views/dashboard/zero-python/current",
                        "query_string": urlencode(
                            {
                                "marimo_studio_client": "browser-client-1234",
                                "revision": request.snapshot.revision,
                            }
                        ).encode(),
                    }
                ),
                registry,
                "dashboard",
                "current",
                clients=clients,
                allow_refresh=False,
            )
            assert response.status_code == 200
            assert (
                json.loads(bytes(response.body))["prepared"]["instance"]
                == current.instance
            )
        finally:
            await registry.close()
            await clients.close()

    asyncio.run(scenario())
