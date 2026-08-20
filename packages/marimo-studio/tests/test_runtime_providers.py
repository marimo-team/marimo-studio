from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._capabilities import (
    PreparedRuntimeState,
    RuntimeProjectionServices,
    ServerContext,
    ServerHandle,
)
from marimo_studio._runtime import (
    SERVER_RUNTIME,
    WASM_RUNTIME,
    ZERO_PYTHON_RUNTIME,
    RuntimeDescriptor,
    RuntimeProjections,
)
from marimo_studio._server.prepared_views import PreparedViewRequest
from marimo_studio._server.presentation import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._server.presentation_payload import build_runtime_config
from marimo_studio._server.publication_runtime import publication_runtime_projector
from marimo_studio._server.runtimes import (
    RuntimeAuthority,
    RuntimeProjection,
    RuntimeProjectionRequest,
    RuntimeRegistry,
    ServerRuntime,
    WasmRuntime,
    ZeroPythonRuntime,
    create_runtime_registry,
    projection_requirements,
)
from marimo_studio.errors import (
    PublicationUnavailableError,
    RuntimeSelectionError,
    TemplateError,
)

from .app_helpers import configured
from .helpers import replace_app_shell


class _Publications:
    def __init__(self, *instances: str, current: str | None = None) -> None:
        self.instances = iter(instances)
        self.current_instance = current
        self.requests: list[PreparedViewRequest] = []
        self.current_requests: list[tuple[str, str, str]] = []

    async def prepare(self, request: PreparedViewRequest) -> Any:
        self.requests.append(request)
        return self._selection(next(self.instances))

    def current(self, view: str, binding_id: str, revision: str) -> Any | None:
        self.current_requests.append((view, binding_id, revision))
        if self.current_instance is None:
            return None
        return self._selection(self.current_instance)

    async def selection(
        self,
        view: str,
        binding_id: str,
        revision: str,
    ) -> Any | None:
        return self.current(view, binding_id, revision)

    @staticmethod
    def _selection(instance: str) -> SimpleNamespace:
        return SimpleNamespace(
            instance=instance,
            plan_digest="d" * 64,
        )


class _BrowserProjection:
    instance = "browser-instance"

    def runtime_data(self) -> dict[str, object]:
        return {"code": "import marimo", "filename": "analysis.py"}


class _Browser:
    def project(self, *_args: object, **_kwargs: object) -> _BrowserProjection:
        return _BrowserProjection()


class _Sessions:
    def live_cells(self, *_args: object, **_kwargs: object) -> None:
        return None


class _EditorControls:
    async def bindings(
        self,
        context: ServerContext,
        session_id: str,
        notebook_revision: str,
        control_revision: int,
    ) -> dict[str, dict[str, object]]:
        del context, session_id, notebook_revision, control_revision
        return {}


def _context(notebook: Path) -> ServerContext:
    return ServerContext(
        notebook=notebook,
        file_key="nested/analysis.py",
        base_url="/parent/base",
        internal_url="http://127.0.0.1:4312/parent/base/",
        mode="edit",
        dev=True,
        routing_query=(("file", "nested/analysis.py"),),
        user_config={},
        config_overrides={},
        server_token="server-token",
        handle=ServerHandle(object()),
    )


def _request(
    notebook: Path,
    publications: _Publications,
    *,
    authority: RuntimeAuthority = "edit",
    session_id: str | None = "s_123456",
    binding_id: str | None = "browser-client-1234",
    with_services: bool = True,
) -> RuntimeProjectionRequest:
    snapshot = NotebookPresentation(notebook).snapshot("dashboard")
    return RuntimeProjectionRequest(
        snapshot=snapshot,
        context=_context(notebook),
        authority=authority,
        session_id=session_id,
        binding_id=binding_id,
        services=(
            RuntimeProjectionServices(
                prepared=publication_runtime_projector(cast(Any, publications)),
                editor_controls=_EditorControls(),
            )
            if with_services
            else None
        ),
    )


def test_runtime_registry_exposes_exact_provider_descriptors() -> None:
    registry = create_runtime_registry(cast(Any, _Sessions()), cast(Any, _Browser()))

    assert registry.descriptors == (
        SERVER_RUNTIME,
        WASM_RUNTIME,
        ZERO_PYTHON_RUNTIME,
    )


def test_server_runtime_rejects_nested_authored_projection_hosts(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    template = studio.views["dashboard"].template
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            '<marimo-output value="doubled">'
            '<marimo-cell name="result"></marimo-cell>'
            "</marimo-output>",
        ),
        encoding="utf-8",
    )

    with pytest.raises(TemplateError, match="cannot be nested"):
        _request(studio.notebook, _Publications())


def test_runtime_request_repr_redacts_server_authority(notebook_path: Path) -> None:
    studio = configured(notebook_path)
    request = _request(studio.notebook, _Publications(), with_services=False)

    assert "server-token" not in repr(request.context)
    assert "server-token" not in repr(request)


def test_runtime_registry_excludes_provider_missing_required_projection(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    request = _request(studio.notebook, _Publications())

    class PartialRuntime:
        descriptor = RuntimeDescriptor(
            id="partial",
            label="Partial",
            description="Projects cells and values",
            execution="prepared",
            projections=RuntimeProjections(cell=True, output=False, value=True),
            controls="none",
            query="none",
            preparation="on-select",
            session="none",
        )

        async def project(
            self,
            _request: RuntimeProjectionRequest,
        ) -> object:
            raise AssertionError("unavailable runtime was projected")

        def supports(
            self,
            _context: ServerContext,
            requirements: RuntimeProjections,
        ) -> bool:
            return not requirements.output

    registry = RuntimeRegistry((cast(Any, PartialRuntime()),))
    requirements = projection_requirements(request.snapshot)

    assert registry.available(studio, request.context, requirements) == ()
    with pytest.raises(RuntimeSelectionError, match=r"partial.*unavailable"):
        registry.select(studio, request.context, "partial", requirements)


def test_runtime_availability_separates_edit_run_and_projection_free_views(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    request = _request(studio.notebook, _Publications())
    registry = create_runtime_registry(cast(Any, _Sessions()), cast(Any, _Browser()))
    requirements = projection_requirements(request.snapshot)
    run_studio = replace(
        studio,
        runtimes=("server", "wasm", "zero-python"),
    )
    run_context = replace(request.context, mode="run")

    assert registry.available(studio, request.context, requirements) == (
        "server",
        "wasm",
        "zero-python",
    )
    assert registry.available(run_studio, run_context, requirements) == (
        "server",
        "wasm",
    )
    assert registry.available(
        studio,
        request.context,
        RuntimeProjections(cell=False, output=False, value=False),
    ) == ("server", "wasm")
    selected_run, _available = registry.select(
        replace(run_studio, default_runtime="zero-python"),
        run_context,
        None,
        requirements,
    )
    selected_static, _available = registry.select(
        replace(studio, default_runtime="zero-python"),
        request.context,
        None,
        RuntimeProjections(cell=False, output=False, value=False),
    )
    assert selected_run.descriptor.id == "server"
    assert selected_static.descriptor.id == "server"


def test_server_and_wasm_providers_keep_static_projection_contracts(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    request = _request(
        studio.notebook,
        _Publications(current="a" * 64),
        with_services=False,
    )
    expected = request.snapshot.resolved.runtime_cell_bindings(
        None,
        required_aliases=request.snapshot.resolved.views["dashboard"].cell_aliases,
    )

    server = asyncio.run(ServerRuntime(cast(Any, _Sessions())).project(request))
    wasm = asyncio.run(WasmRuntime(cast(Any, _Browser())).project(request))

    assert server.cell_bindings == expected
    assert server.control_source == "editor"
    assert (
        server.native_control_cells
        == request.snapshot.resolved.runtime_control_cells(None)
    )
    assert wasm.cell_bindings == expected
    assert wasm.control_source is None
    assert wasm.native_control_cells == request.snapshot.resolved.runtime_control_cells(
        None
    )
    assert wasm.instance == "browser-instance"


def test_server_control_config_does_not_wait_for_prepared_runtime(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    request = _request(studio.notebook, _Publications(), with_services=False)

    class Services:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def project(
            self,
            snapshot: PresentationSnapshot,
            context: ServerContext,
            authority: RuntimeAuthority,
            session_id: str | None,
            binding_id: str | None,
        ) -> PreparedRuntimeState:
            del snapshot, context, authority, session_id, binding_id
            self.started.set()
            await self.release.wait()
            return PreparedRuntimeState(
                instance="prepared-instance",
                data={"manifestUrl": "/current", "planDigest": "d" * 64},
            )

        async def bindings(
            self,
            context: ServerContext,
            session_id: str,
            notebook_revision: str,
            control_revision: int,
        ) -> dict[str, dict[str, object]]:
            del context, session_id, notebook_revision, control_revision
            return {
                "editor-root": {"input": "filters", "path": ()},
                "editor-region": {
                    "input": "filters",
                    "path": ({"kind": "key", "value": "region"},),
                },
            }

    async def exercise() -> dict[str, object]:
        service = Services()
        services = RuntimeProjectionServices(
            prepared=service,
            editor_controls=service,
        )
        scoped = replace(request, services=services, control_revision=0)
        preparing = asyncio.create_task(ZeroPythonRuntime().project(scoped))
        await service.started.wait()
        config = await asyncio.wait_for(
            build_runtime_config(scoped, ServerRuntime(cast(Any, _Sessions()))),
            timeout=0.1,
        )
        service.release.set()
        await preparing
        return config

    config = asyncio.run(exercise())

    runtime = cast(dict[str, object], config["runtime"])
    controls = cast(dict[str, object], runtime["controls"])
    assert controls["bindings"] == {
        "editor-root": {"input": "filters", "path": []},
        "editor-region": {
            "input": "filters",
            "path": [{"kind": "key", "value": "region"}],
        },
    }
    assert "native" in controls


def test_python_runtime_config_matches_the_browser_fixture() -> None:
    view = SimpleNamespace(diagnostics=())
    workspace = SimpleNamespace(
        views={"dashboard": view},
        show_cell_logs=True,
        notebook=Path("/workspace/notebook.py"),
    )
    snapshot = cast(
        PresentationSnapshot,
        SimpleNamespace(
            revision="presentation-revision",
            notebook_revision="notebook-source-revision",
            view_name="dashboard",
            resolved=SimpleNamespace(
                workspace=workspace,
                views=workspace.views,
                notebook=SimpleNamespace(app_config={}),
            ),
        ),
    )
    context = ServerContext(
        notebook=Path("/workspace/notebook.py"),
        file_key="notebook.py",
        base_url="/proxy/app",
        internal_url="http://127.0.0.1:4312/proxy/app/",
        mode="edit",
        dev=True,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="server-token",
        handle=ServerHandle(object()),
    )

    class Services:
        async def project(
            self,
            snapshot: PresentationSnapshot,
            context: ServerContext,
            authority: RuntimeAuthority,
            session_id: str | None,
            binding_id: str | None,
        ) -> PreparedRuntimeState:
            del snapshot, context, authority, session_id, binding_id
            raise AssertionError("server config invoked prepared runtime projection")

        async def bindings(
            self,
            context: ServerContext,
            session_id: str,
            notebook_revision: str,
            control_revision: int,
        ) -> dict[str, dict[str, object]]:
            del context, session_id, notebook_revision, control_revision
            return {
                "editor-root": {"input": "filters", "path": ()},
                "editor-region": {
                    "input": "filters",
                    "path": ({"kind": "key", "value": "region"},),
                },
                "editor-region-copy": {
                    "input": "filters",
                    "path": ({"kind": "key", "value": "region"},),
                },
            }

    class Provider:
        descriptor = SERVER_RUNTIME

        async def project(
            self,
            request: RuntimeProjectionRequest,
        ) -> RuntimeProjection:
            del request
            return RuntimeProjection(
                instance="server-instance",
                data={
                    "url": "/proxy/app/",
                    "serverToken": "server-token",
                    "fileKey": "notebook.py",
                    "preserveSession": False,
                },
                cell_bindings={"plot": {"kind": "name", "value": "plot"}},
                value_bindings={
                    "context.label": {
                        "variable": "context",
                        "cell": {"kind": "id", "value": "context-cell-id"},
                    }
                },
                output_bindings={
                    "context.table": {
                        "variable": "context",
                        "cell": {"kind": "id", "value": "context-cell-id"},
                    }
                },
                control_source="editor",
                native_control_cells={"cell:v1:semantic": "MJUe"},
            )

        def supports(
            self,
            context: ServerContext,
            requirements: RuntimeProjections,
        ) -> bool:
            del context, requirements
            return True

    service = Services()
    payload = asyncio.run(
        build_runtime_config(
            RuntimeProjectionRequest(
                snapshot=snapshot,
                context=context,
                authority="edit",
                session_id="s_123456",
                binding_id="browser-client-1234",
                services=RuntimeProjectionServices(
                    prepared=service,
                    editor_controls=service,
                ),
                control_revision=0,
            ),
            Provider(),
        )
    )
    fixture = (
        Path(__file__).parents[2] / "protocol" / "fixtures" / "runtime-config.json"
    )

    assert payload == json.loads(fixture.read_text(encoding="utf-8"))


def test_zero_python_provider_uses_trusted_internal_endpoint(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    instance = "a" * 64
    publications = _Publications(instance)
    request = _request(studio.notebook, publications)
    request.snapshot.resolved.aliases["unused"] = request.snapshot.resolved.aliases[
        "result"
    ]

    projection = asyncio.run(ZeroPythonRuntime().project(request))

    assert projection.instance == instance
    assert projection.data == {
        "manifestUrl": (
            "/parent/base/_marimo-studio/views/dashboard/zero-python/"
            "current?file=nested%2Fanalysis.py&"
            "marimo_studio_client=browser-client-1234&"
            f"revision={request.snapshot.revision}"
        ),
        "planDigest": "d" * 64,
    }
    assert len(publications.requests) == 1
    prepared_request = publications.requests[0]
    assert prepared_request.server == "http://127.0.0.1:4312/parent/base/"
    assert prepared_request.server_token == "server-token"
    assert prepared_request.session_id == "s_123456"
    assert prepared_request.binding_id == "browser-client-1234"
    assert set(projection.cell_bindings) == {"result"}


def test_zero_python_provider_keeps_instance_for_current_state_refresh(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    instance = "b" * 64
    publications = _Publications(instance, instance)
    request = _request(studio.notebook, publications)

    first = asyncio.run(ZeroPythonRuntime().project(request))
    refreshed = asyncio.run(ZeroPythonRuntime().project(request))

    assert first.instance == refreshed.instance == instance
    assert len(publications.requests) == 2


def test_sessionless_zero_python_provider_reports_publication_pending(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    publications = _Publications()
    request = _request(studio.notebook, publications, session_id=None)

    with pytest.raises(
        PublicationUnavailableError,
        match="editor session",
    ):
        asyncio.run(ZeroPythonRuntime().project(request))

    assert publications.requests == []


def test_read_authority_reuses_verified_publication_without_capture(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    instance = "c" * 64
    publications = _Publications(current=instance)
    request = _request(
        studio.notebook,
        publications,
        authority="read",
        session_id=None,
    )

    projection = asyncio.run(ZeroPythonRuntime().project(request))

    assert projection.instance == instance
    assert publications.current_requests == [
        (
            "dashboard",
            "browser-client-1234",
            request.snapshot.revision,
        )
    ]
    assert publications.requests == []
