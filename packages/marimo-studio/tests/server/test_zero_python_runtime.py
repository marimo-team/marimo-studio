from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._server.publication_runtime import (
    PreparedRuntimeState,
    PublicationRuntimeProjector,
)
from marimo_studio._server.records import ServerContext, ServerHandle
from marimo_studio._server.runtime.catalog import ZeroPythonRuntime


def test_zero_python_runtime_uses_notebook_scoped_publication_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_owner = object()
    scope = SimpleNamespace(publications=publication_owner)
    notebooks = SimpleNamespace(get=lambda _notebook: scope)
    calls: list[tuple[object, ...]] = []

    async def project(
        self: PublicationRuntimeProjector,
        snapshot: object,
        context: object,
        authority: str,
        session_id: str | None,
        binding_id: str | None,
        presentation_session_id: str | None,
    ) -> PreparedRuntimeState:
        calls.append(
            (
                self,
                snapshot,
                context,
                authority,
                session_id,
                binding_id,
                presentation_session_id,
            )
        )
        return PreparedRuntimeState("a" * 64, {"manifestUrl": "/prepared"})

    monkeypatch.setattr(PublicationRuntimeProjector, "project", project)
    resolved = SimpleNamespace(runtime_cell_refs=lambda _cells: {"cell-ref": "cell-id"})
    snapshot = SimpleNamespace(resolved=resolved)
    context = ServerContext(
        notebook=tmp_path / "notebook.py",
        file_key="notebook.py",
        base_url="",
        mode="edit",
        dev=True,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="token",
        handle=ServerHandle(object()),
        internal_url="http://127.0.0.1:4312/",
    )
    runtime = ZeroPythonRuntime(cast(Any, notebooks))

    result = asyncio.run(
        runtime.project(
            cast(Any, snapshot),
            context,
            "s_editor",
            "browser-client",
            "s_preview",
        )
    )

    assert result.runtime_id == "zero-python"
    assert result.instance == "a" * 64
    assert result.cell_refs == {"cell-ref": "cell-id"}
    assert calls[0][3:] == (
        "edit",
        "s_editor",
        "browser-client",
        "s_preview",
    )
    assert (
        cast(PublicationRuntimeProjector, calls[0][0])._publications
        is publication_owner
    )
