from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import marimo_studio._compat.kernel_values.kernel as kernel_values_module
from marimo_studio._compat.kernel_values.authorization import (
    authorized_output_arguments,
    authorized_value_arguments,
)
from marimo_studio._compat.kernel_values.kernel import _KernelBridgeLifespan
from marimo_studio._compat.kernel_values.query_authorization import (
    authorized_query_arguments,
)
from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    QUERY_OPERATION_QUERY_PARAM,
)
from marimo_studio._server.presentation.query_state import query_fingerprint

from .values_test_support import (
    _bound_projection,
    _encoded_json,
    _native_output_context,
)


def test_untitled_kernel_activates_after_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module
    from marimo._utils.lifespans import Lifespans

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")

    class Registry:
        def __init__(self) -> None:
            self.registered: list[str] = []
            self.deleted: list[str] = []

        def register(self, namespace: str, _function: object) -> None:
            self.registered.append(namespace)

        def delete(self, namespace: str) -> None:
            self.deleted.append(namespace)

    class Kernel:
        _lifespan: Any = None
        app_metadata = SimpleNamespace(filename=None)

    class Context:
        filename = None
        function_registry = Registry()
        query_params: dict[str, str]
        _kernel = Kernel()

    context = Context()
    context.query_params = {}
    monkeypatch.setattr(runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(kernel_context_module, "KernelRuntimeContext", Context)

    async def exercise() -> None:
        aggregate = Lifespans([kernel_values_module.kernel_lifespan])(None)
        context._kernel._lifespan = aggregate
        await aggregate.__aenter__()
        await context._kernel._lifespan.__aenter__()
        registered = [*context.function_registry.registered]
        assert registered
        context._kernel.app_metadata.filename = str(notebook)
        await context._kernel._lifespan.__aenter__()
        assert context.function_registry.registered == registered
        await context._kernel._lifespan.__aenter__()
        assert context.function_registry.registered == registered
        await context._kernel._lifespan.__aexit__(None, None, None)

    asyncio.run(exercise())

    assert context.function_registry.deleted == ["_marimo_studio"]


def test_kernel_reinstantiation_preserves_marimos_full_lifespan_chain() -> None:
    from contextlib import asynccontextmanager

    from marimo._utils.lifespans import Lifespans

    events: list[str] = []

    class Kernel:
        _lifespan: Any = None

    class Context:
        _kernel = Kernel()

    @asynccontextmanager
    async def first(_app: None):
        events.append("first-enter")
        try:
            yield
        finally:
            events.append("first-exit")

    @asynccontextmanager
    async def studio(_app: None):
        events.append("studio-enter")
        kernel_values_module._guard_entered_lifespan(Context())
        try:
            yield
        finally:
            events.append("studio-exit")

    @asynccontextmanager
    async def last(_app: None):
        events.append("last-enter")
        try:
            yield
        finally:
            events.append("last-exit")

    async def exercise() -> None:
        aggregate = Lifespans([first, studio, last])(None)
        Context._kernel._lifespan = aggregate
        await aggregate.__aenter__()
        await Context._kernel._lifespan.__aenter__()
        await Context._kernel._lifespan.__aexit__(None, None, None)

    asyncio.run(exercise())

    assert events == [
        "first-enter",
        "studio-enter",
        "last-enter",
        "last-exit",
        "studio-exit",
        "first-exit",
    ]


def test_kernel_lifespan_rejects_retry_after_setup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module
    from marimo._utils.lifespans import Lifespans

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")

    class Registry:
        def __init__(self) -> None:
            self.registered: list[str] = []
            self.deleted: list[str] = []

        def register(self, namespace: str, _: object) -> None:
            self.registered.append(namespace)

        def delete(self, namespace: str) -> None:
            self.deleted.append(namespace)

    class Kernel:
        _lifespan: Any = None

    class Context:
        filename = str(notebook)
        function_registry = Registry()
        query_params: dict[str, str]
        _kernel = Kernel()

    context = Context()
    context.query_params = {}
    monkeypatch.setattr(runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(kernel_context_module, "KernelRuntimeContext", Context)

    @asynccontextmanager
    async def failing(_app: None):
        raise RuntimeError("later lifespan failed")
        yield

    async def exercise() -> None:
        aggregate = Lifespans([kernel_values_module.kernel_lifespan, failing])(None)
        context._kernel._lifespan = aggregate
        with pytest.raises(RuntimeError, match="later lifespan failed"):
            await aggregate.__aenter__()
        with pytest.raises(RuntimeError, match="kernel lifespan setup failed"):
            await context._kernel._lifespan.__aenter__()

    asyncio.run(exercise())

    assert context.function_registry.registered == [
        "_marimo_studio",
        "_marimo_studio",
        "_marimo_studio",
    ]
    assert context.function_registry.deleted == ["_marimo_studio"]


def test_kernel_lifespan_cleans_a_partially_registered_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module
    from marimo._utils.lifespans import Lifespans

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")

    class Registry:
        def __init__(self) -> None:
            self.calls = 0
            self.deleted: list[str] = []

        def register(self, _namespace: str, _function: object) -> None:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("registration failed")

        def delete(self, namespace: str) -> None:
            self.deleted.append(namespace)

    class Kernel:
        _lifespan: Any = None

    class Context:
        filename = str(notebook)
        function_registry = Registry()
        query_params: dict[str, str]
        _kernel = Kernel()

    context = Context()
    context.query_params = {}
    monkeypatch.setattr(runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(kernel_context_module, "KernelRuntimeContext", Context)

    async def exercise() -> None:
        aggregate = Lifespans([kernel_values_module.kernel_lifespan])(None)
        context._kernel._lifespan = aggregate
        with pytest.raises(RuntimeError, match="registration failed"):
            await aggregate.__aenter__()
        with pytest.raises(RuntimeError, match="kernel lifespan setup failed"):
            await context._kernel._lifespan.__aenter__()

    asyncio.run(exercise())

    assert context.function_registry.calls == 2
    assert context.function_registry.deleted == ["_marimo_studio"]


def test_kernel_lifespan_registers_before_the_first_view_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    tmp_path.joinpath("pyproject.toml").write_text(
        """\
[tool.marimo-studio]
notebook = "notebook.py"
default = "dashboard"
""",
        encoding="utf-8",
    )

    class Registry:
        def __init__(self) -> None:
            self.registered: list[str] = []
            self.deleted: list[str] = []

        def register(self, namespace: str, _: object) -> None:
            self.registered.append(namespace)

        def delete(self, namespace: str) -> None:
            self.deleted.append(namespace)

    class Context:
        filename = str(notebook)
        function_registry = Registry()
        query_params: dict[str, str]
        _kernel = object()

    context = Context()
    context.query_params = {}
    monkeypatch.setattr(runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(kernel_context_module, "KernelRuntimeContext", Context)
    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        lambda: lambda: None,
    )

    async def exercise() -> None:
        async with _KernelBridgeLifespan():
            assert context.function_registry.registered == [
                "_marimo_studio",
                "_marimo_studio",
                "_marimo_studio",
            ]

    asyncio.run(exercise())

    assert context.function_registry.deleted == ["_marimo_studio"]


@pytest.mark.parametrize("initially_untitled", [False, True])
def test_kernel_lifespan_activates_after_the_first_view_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    initially_untitled: bool,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")

    class Kernel:
        def __init__(self) -> None:
            self.app_metadata = SimpleNamespace(
                filename=None if initially_untitled else str(notebook)
            )
            self.globals = {"summary": {"papers": 3_877}}
            self.graph = SimpleNamespace(
                cells={
                    "runtime-projection": SimpleNamespace(
                        code="summary = None",
                        defs={"summary"},
                    )
                },
                ancestors=lambda _cell_id: set(),
            )
            self.lock_count = 0

        @contextmanager
        def lock_globals(self):
            self.lock_count += 1
            yield

    cache_activations: list[bool] = []
    cache_releases: list[bool] = []

    def keep_cached_cells_compatible() -> Any:
        cache_activations.append(True)
        return lambda: cache_releases.append(True)

    current = _native_output_context()
    current.filename = None if initially_untitled else str(notebook)
    current._kernel = Kernel()
    monkeypatch.setattr(runtime_context, "get_context", lambda: current)
    monkeypatch.setattr(
        kernel_context_module,
        "KernelRuntimeContext",
        type(current),
    )
    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        keep_cached_cells_compatible,
    )

    async def exercise() -> None:
        async with _KernelBridgeLifespan():
            functions = current.function_registry.namespaces["_marimo_studio"].functions
            assert set(functions) == {
                "read_values",
                "render_values",
                "sync_query",
            }
            read = functions["read_values"]
            projection = _bound_projection("summary.papers")

            before = cast(
                dict[str, Any],
                read(
                    {
                        **authorized_value_arguments(
                            "revision-1", (projection,), "preview-a"
                        ),
                        "max_value_bytes": 1_000,
                    }
                ),
            )
            assert before["values"] == {}
            assert (
                cast(dict[str, Any], before["errors"])["summary.papers"]["code"]
                == "unknown-selector"
            )
            assert not cache_activations
            assert current._kernel.lock_count == 0

            view = tmp_path / "__marimo__" / "studio" / "notebook" / "dashboard"
            view.mkdir(parents=True)
            view.joinpath("index.html").write_text(
                '<span mo-value="summary.papers"></span>',
                encoding="utf-8",
            )
            tmp_path.joinpath("pyproject.toml").write_text(
                """\
[tool.marimo-studio]
notebook = "notebook.py"
default = "dashboard"
""",
                encoding="utf-8",
            )

            current._kernel.app_metadata.filename = str(notebook)
            after = cast(
                dict[str, Any],
                read(
                    {
                        **authorized_value_arguments(
                            "revision-1", (projection,), "preview-a"
                        ),
                        "max_value_bytes": 1_000,
                    }
                ),
            )
            assert after["values"] == {
                "summary.papers": _encoded_json(3_877),
            }
            assert cache_activations == [True]
            assert current._kernel.lock_count == 1

            live_cell = current._kernel.graph.cells["runtime-projection"]
            live_cell.code = "moved = None"
            live_cell.defs = {"moved"}
            stale = cast(
                dict[str, Any],
                read(
                    {
                        **authorized_value_arguments(
                            "revision-1", (projection,), "preview-a"
                        ),
                        "max_value_bytes": 1_000,
                    }
                ),
            )
            assert stale["errors"]["*"]["code"] == "stale-projection-binding"

            forged_value = {
                **authorized_value_arguments("revision-1", (projection,), "preview-a"),
                "authorization": "0" * 64,
                "max_value_bytes": 1_000,
            }
            rejected_value = cast(dict[str, Any], read(forged_value))
            assert rejected_value["errors"]["*"]["code"] == (
                "projection-authorization-invalid"
            )

            output = _bound_projection("summary.papers", "output")
            forged_output = {
                **authorized_output_arguments(
                    "revision-1",
                    (output,),
                    (output,),
                    "preview-a",
                ),
                "authorization": "0" * 64,
                "max_output_bytes": 1_000,
            }
            rejected_output = cast(
                dict[str, Any],
                functions["render_values"](forged_output),
            )
            assert rejected_output["errors"]["*"]["code"] == (
                "projection-authorization-invalid"
            )

    try:
        with current.install():
            asyncio.run(exercise())
    finally:
        current.virtual_file_registry.shutdown()

    assert current.function_registry.namespaces == {}
    assert cache_releases == [True]


def test_kernel_lifespan_leaves_export_owned_kernel_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    tmp_path.joinpath("pyproject.toml").write_text(
        """\
[tool.marimo-studio]
notebook = "notebook.py"
default = "dashboard"
""",
        encoding="utf-8",
    )
    cache_activations: list[bool] = []
    current = _native_output_context()
    current.filename = str(notebook)
    current._kernel = SimpleNamespace()
    monkeypatch.setattr(runtime_context, "get_context", lambda: current)
    monkeypatch.setattr(
        kernel_context_module,
        "KernelRuntimeContext",
        type(current),
    )
    monkeypatch.setattr(kernel_values_module, "is_owned_session", lambda: True)

    def activate_cache_compatibility() -> Any:
        cache_activations.append(True)
        return lambda: None

    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        activate_cache_compatibility,
    )
    lifespan = _KernelBridgeLifespan()

    async def exercise() -> None:
        async with lifespan:
            assert lifespan._output_renderer is None
            assert lifespan._value_encoder is None
            assert lifespan._observation_ledger is None

    try:
        with current.install():
            asyncio.run(exercise())
    finally:
        current.virtual_file_registry.shutdown()

    assert cache_activations == []


def test_shared_kernel_accepts_query_updates_from_each_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging import notification_utils
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    current = _native_output_context()
    current.filename = str(notebook)
    current._kernel = SimpleNamespace(state_updates={})
    values: dict[str, str | list[str]] = {}
    current._query_params = SimpleNamespace(
        get=values.get,
        to_dict=lambda: dict(values),
        set=values.__setitem__,
        remove=lambda key: values.pop(key, None),
    )
    current.stream = object()
    monkeypatch.setattr(runtime_context, "get_context", lambda: current)
    monkeypatch.setattr(kernel_context_module, "KernelRuntimeContext", type(current))
    monkeypatch.setattr(notification_utils, "broadcast_notification", lambda *_: None)
    monkeypatch.setattr(_KernelBridgeLifespan, "_activate", lambda *_: True)

    async def exercise() -> None:
        async with _KernelBridgeLifespan():
            function = current.function_registry.namespaces["_marimo_studio"].functions[
                "sync_query"
            ]

            async def update(
                consumer: str, binding: int, generation: int, region: str
            ) -> Any:
                return await function(
                    authorized_query_arguments(
                        query={"region": region},
                        fingerprint=query_fingerprint({"region": region}),
                        operation_id=f"query_{generation}",
                        binding_generation=binding,
                        query_generation=generation,
                        deadline=time.monotonic() + 60,
                        session_id=consumer,
                        notebook=notebook,
                    )
                )

            assert (await update("s_first1", 1, 0, "emea"))["status"] == "applied"
            assert (await update("s_second", 2, 0, "apac"))["status"] == "applied"
            assert (await update("s_first1", 1, 2, "americas"))["status"] == "applied"
            assert values == {"region": "americas"}
            assert (await update("s_first1", 1, 1, "stale"))["status"] == "superseded"
            assert values == {"region": "americas"}

    try:
        with current.install():
            asyncio.run(exercise())
    finally:
        current.virtual_file_registry.shutdown()


def test_kernel_query_sync_labels_its_echo_and_preserves_private_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._messaging import notification_utils
    from marimo._runtime import context as runtime_context
    from marimo._runtime.context import kernel_context as kernel_context_module

    notebook = tmp_path / "notebook.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    view = tmp_path / "__marimo__" / "studio" / "notebook" / "dashboard"
    view.mkdir(parents=True)
    view.joinpath("index.html").write_text("<main></main>", encoding="utf-8")
    tmp_path.joinpath("pyproject.toml").write_text(
        """\
[tool.marimo-studio]
notebook = "notebook.py"
default = "dashboard"
""",
        encoding="utf-8",
    )
    events: list[tuple[object, ...]] = []

    class QueryParams:
        def __init__(self) -> None:
            self.values: dict[str, str | list[str]] = {
                "session_id": "s_private",
                "runtime": "server",
                DOCUMENT_LIFECYCLE_QUERY_PARAM: "6",
                "old": "value",
            }

        def to_dict(self) -> dict[str, str | list[str]]:
            return dict(self.values)

        def get(self, key: str) -> str | list[str] | None:
            return self.values.get(key)

        def remove(self, key: str) -> None:
            events.append(("remove", key))
            self.values.pop(key, None)

        def set(self, key: str, value: str | list[str]) -> None:
            events.append(("set", key, value))
            self.values[key] = value

    def record_notification(notification: object, _stream: object) -> None:
        events.append(
            (
                type(notification).__name__,
                getattr(notification, "key", None),
                getattr(notification, "value", None),
            )
        )

    current = _native_output_context()
    current.filename = str(notebook)
    current._kernel = SimpleNamespace(state_updates={})
    current._query_params = QueryParams()
    current.stream = object()
    monkeypatch.setattr(runtime_context, "get_context", lambda: current)
    monkeypatch.setattr(
        kernel_context_module,
        "KernelRuntimeContext",
        type(current),
    )
    monkeypatch.setattr(
        notification_utils,
        "broadcast_notification",
        record_notification,
    )
    monkeypatch.setattr(
        kernel_values_module,
        "keep_cached_cells_compatible",
        lambda: lambda: None,
    )

    async def exercise() -> None:
        async with _KernelBridgeLifespan():
            function = current.function_registry.namespaces["_marimo_studio"].functions[
                "sync_query"
            ]
            query_1_deadline = time.monotonic() + 60

            def authorized(arguments: dict[str, object]) -> dict[str, object]:
                return authorized_query_arguments(
                    query=cast(dict[str, str | list[str]], arguments["query"]),
                    fingerprint=cast(str, arguments["fingerprint"]),
                    operation_id=cast(str, arguments["operation_id"]),
                    binding_generation=cast(int, arguments["binding_generation"]),
                    query_generation=cast(int, arguments["query_generation"]),
                    deadline=cast(float, arguments["deadline"]),
                    session_id="s_123456",
                    notebook=notebook,
                )

            applied = await function(
                authorized(
                    {
                        "query": {
                            "region": "emea",
                            "session_id": "s_injected",
                            "runtime": "wasm",
                            DOCUMENT_LIFECYCLE_QUERY_PARAM: "7",
                            QUERY_OPERATION_QUERY_PARAM: "query_injected",
                        },
                        "operation_id": "query_1",
                        "fingerprint": query_fingerprint({"region": "emea"}),
                        "binding_generation": 1,
                        "query_generation": 0,
                        "deadline": query_1_deadline,
                    }
                )
            )
            repeated = await function(
                authorized(
                    {
                        "query": {"region": "emea"},
                        "operation_id": "query_1",
                        "fingerprint": query_fingerprint({"region": "emea"}),
                        "binding_generation": 1,
                        "query_generation": 0,
                        "deadline": query_1_deadline,
                    }
                )
            )
            with pytest.raises(ValueError, match="different query"):
                await function(
                    authorized(
                        {
                            "query": {"region": "apac"},
                            "operation_id": "query_1",
                            "fingerprint": query_fingerprint({"region": "apac"}),
                            "binding_generation": 1,
                            "query_generation": 0,
                            "deadline": query_1_deadline,
                        }
                    )
                )
            newer = await function(
                authorized(
                    {
                        "query": {"region": "apac"},
                        "operation_id": "query_2",
                        "fingerprint": query_fingerprint({"region": "apac"}),
                        "binding_generation": 1,
                        "query_generation": 2,
                        "deadline": time.monotonic() + 60,
                    }
                )
            )
            superseded = await function(
                authorized(
                    {
                        "query": {"region": "stale"},
                        "operation_id": "query_stale",
                        "fingerprint": query_fingerprint({"region": "stale"}),
                        "binding_generation": 1,
                        "query_generation": 1,
                        "deadline": time.monotonic() + 60,
                    }
                )
            )
            rebound = await function(
                authorized(
                    {
                        "query": {"region": "americas"},
                        "operation_id": "query_3",
                        "fingerprint": query_fingerprint({"region": "americas"}),
                        "binding_generation": 2,
                        "query_generation": 0,
                        "deadline": time.monotonic() + 60,
                    }
                )
            )
            expired = await function(
                authorized(
                    {
                        "query": {"region": "expired"},
                        "operation_id": "query_expired",
                        "fingerprint": query_fingerprint({"region": "expired"}),
                        "binding_generation": 3,
                        "query_generation": 0,
                        "deadline": time.monotonic() - 1,
                    }
                )
            )
            unauthorized = authorized(
                {
                    "query": {"region": "blocked"},
                    "operation_id": "query_blocked",
                    "fingerprint": query_fingerprint({"region": "blocked"}),
                    "binding_generation": 3,
                    "query_generation": 1,
                    "deadline": time.monotonic() + 60,
                }
            )
            unauthorized["authorization"] = ""
            with pytest.raises(ValueError, match="identity is invalid"):
                await function(unauthorized)
            tampered = authorized(
                {
                    "query": {"region": "blocked"},
                    "operation_id": "query_tampered",
                    "fingerprint": query_fingerprint({"region": "blocked"}),
                    "binding_generation": 3,
                    "query_generation": 2,
                    "deadline": time.monotonic() + 60,
                }
            )
            tampered["query_generation"] = 3
            with pytest.raises(ValueError, match="identity is invalid"):
                await function(tampered)
            assert (
                applied
                == repeated
                == {
                    "operation_id": "query_1",
                    "fingerprint": query_fingerprint({"region": "emea"}),
                    "binding_generation": 1,
                    "query_generation": 0,
                    "deadline": query_1_deadline,
                    "status": "applied",
                }
            )
            assert newer["status"] == "applied"
            assert superseded["status"] == "superseded"
            assert rebound["status"] == "applied"
            assert expired["status"] == "expired"

    try:
        with current.install():
            asyncio.run(exercise())
    finally:
        current.virtual_file_registry.shutdown()

    assert current.query_params.values == {
        "session_id": "s_private",
        "runtime": "server",
        DOCUMENT_LIFECYCLE_QUERY_PARAM: "6",
        "region": "americas",
    }
    assert events == [
        (
            "QueryParamsSetNotification",
            QUERY_OPERATION_QUERY_PARAM,
            "query_1",
        ),
        ("remove", "old"),
        ("set", "region", "emea"),
        (
            "QueryParamsDeleteNotification",
            QUERY_OPERATION_QUERY_PARAM,
            None,
        ),
        (
            "QueryParamsSetNotification",
            QUERY_OPERATION_QUERY_PARAM,
            "query_1",
        ),
        (
            "QueryParamsDeleteNotification",
            QUERY_OPERATION_QUERY_PARAM,
            None,
        ),
        (
            "QueryParamsSetNotification",
            QUERY_OPERATION_QUERY_PARAM,
            "query_2",
        ),
        ("set", "region", "apac"),
        (
            "QueryParamsDeleteNotification",
            QUERY_OPERATION_QUERY_PARAM,
            None,
        ),
        (
            "QueryParamsSetNotification",
            QUERY_OPERATION_QUERY_PARAM,
            "query_3",
        ),
        ("set", "region", "americas"),
        (
            "QueryParamsDeleteNotification",
            QUERY_OPERATION_QUERY_PARAM,
            None,
        ),
    ]
