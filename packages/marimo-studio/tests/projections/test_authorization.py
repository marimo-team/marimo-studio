"""Protect projection capability authorization."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import PurePosixPath
from threading import Event
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from marimo_export.values import Size, ValueSelector

from marimo_studio._compat.kernel_values import host as projection_host
from marimo_studio._compat.kernel_values.authorization import (
    BoundProjection,
    ProjectionAuthorizationError,
    RuntimeCellBinding,
    authorized_output_arguments,
    authorized_value_arguments,
    verify_output_arguments,
    verify_value_ownership_arguments,
)
from marimo_studio._compat.kernel_values.authorization_key import (
    initialize_projection_authorization_key,
    projection_authorization_key,
    sign_kernel_authorization,
    verify_kernel_authorization,
)
from marimo_studio._compat.kernel_values.host import (
    _bind_projections,
    _build_live_projection_state,
    _executed_signature,
)
from marimo_studio._compat.kernel_values.kernel import _current_selectors
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ResolvedProjection,
)
from marimo_studio._projections.runtime_records import (
    OutputRenderResult,
    ValueReadResult,
)
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio.view_providers import SourceLocation

from ..marimo_compat.values_test_support import (
    _call_projection,
    _install_projection_host,
    _SummarySession,
)


def _live(host: Any, operation: str, session_id: str = "session") -> Any:
    return _call_projection(host, operation, _projection(), session_id)


def _projection() -> ResolvedProjection:
    producer = CellRef("0" * 64, "1" * 64)
    return ResolvedProjection(
        request=ProjectionRequest(
            site_id="site:value:summary",
            instance_id="projection-summary",
            target="summary.total",
        ),
        kind="value",
        source=SourceLocation(PurePosixPath("src/App.tsx"), 2, 3),
        producer=producer,
        selector=ValueSelector("summary.total"),
        dependency_closure=(producer,),
    )


def _projection_with_upstream(
    kind: Literal["cell", "value", "output"] = "value",
) -> tuple[ResolvedProjection, tuple[tuple[CellRef, str, str], ...]]:
    upstream_code = "source = 1"
    producer_code = "summary = {'total': source}"
    upstream, producer = cell_refs((upstream_code, producer_code))
    projection = ResolvedProjection(
        request=ProjectionRequest(
            site_id=f"site:{kind}:summary",
            instance_id=f"projection-{kind}-summary",
            target="summary" if kind == "cell" else "summary.total",
        ),
        kind=kind,
        source=SourceLocation(PurePosixPath("src/App.tsx"), 2, 3),
        producer=producer,
        selector=None if kind == "cell" else ValueSelector("summary.total"),
        dependency_closure=(upstream, producer),
    )
    return projection, (
        (upstream, "runtime-upstream", upstream_code),
        (producer, "runtime-summary", producer_code),
    )


def _bound_with_upstream(
    kind: Literal["value", "output"] = "value",
) -> BoundProjection:
    projection, cells = _projection_with_upstream(kind)
    return BoundProjection(
        projection,
        tuple(RuntimeCellBinding(ref, runtime_id) for ref, runtime_id, _ in cells),
    )


def _verify_bound_projection(
    kind: Literal["value", "output"],
    bound: BoundProjection,
    *,
    revision: str,
) -> Any:
    if kind == "value":
        arguments = authorized_value_arguments(revision, (bound,), "preview-a")
        authorized, _active = verify_value_ownership_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            active_projections=arguments["active_projections"],
            consumer_id=arguments["consumer_id"],
            authorization=arguments["authorization"],
        )
        return authorized
    arguments = authorized_output_arguments(
        revision,
        (bound,),
        (bound,),
        "preview-a",
    )
    authorized, _active = verify_output_arguments(
        revision=arguments["revision"],
        projections=arguments["projections"],
        active_projections=arguments["active_projections"],
        consumer_id=arguments["consumer_id"],
        authorization=arguments["authorization"],
    )
    return authorized


def _projection_with_unresolved_reference(
    kind: Literal["cell", "value", "output"],
) -> tuple[ResolvedProjection, str]:
    producer_code = "summary = missing"
    producer = cell_refs((producer_code,))[0]
    return (
        ResolvedProjection(
            request=ProjectionRequest(
                site_id=f"site:{kind}:summary",
                instance_id=f"projection-{kind}-summary",
                target="summary",
            ),
            kind=kind,
            source=SourceLocation(PurePosixPath("src/App.tsx"), 2, 3),
            producer=producer,
            selector=None if kind == "cell" else ValueSelector("summary"),
            dependency_closure=(producer,),
        ),
        producer_code,
    )


class _Graph:
    def __init__(
        self,
        cells: dict[str, SimpleNamespace],
        parents: dict[str, set[str]] | None = None,
    ) -> None:
        self.cells = cells
        self.parents = parents or {}

    def ancestors(self, cell_id: str) -> set[str]:
        found: set[str] = set()
        pending = list(self.parents.get(cell_id, ()))
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(self.parents.get(current, ()))
        return found


@pytest.fixture(autouse=True)
def _projection_authorization_key() -> None:
    # Studio creates the key at server composition. Tests here sign and verify
    # without a server, so each one creates it instead of relying on whichever
    # test ran first in its worker.
    initialize_projection_authorization_key()


def test_kernel_authorization_uses_canonical_json() -> None:
    initialize_projection_authorization_key()
    first = {"operation": "value", "arguments": {"target": "café", "index": 1}}
    reordered = {"arguments": {"index": 1, "target": "café"}, "operation": "value"}

    authorization = sign_kernel_authorization(first)

    assert authorization == sign_kernel_authorization(reordered)
    assert verify_kernel_authorization(authorization, reordered)
    assert not verify_kernel_authorization(
        authorization,
        {**reordered, "operation": "output"},
    )


@pytest.mark.native_process
def test_parent_authorization_key_is_stable_and_inherited_by_spawned_kernels() -> None:
    initialize_projection_authorization_key()
    first = projection_authorization_key()
    initialize_projection_authorization_key()
    assert projection_authorization_key() is first

    arguments: dict[str, Any] = authorized_value_arguments(
        "revision-1",
        (
            BoundProjection(
                _projection(),
                (
                    RuntimeCellBinding(
                        _projection().producer,
                        "runtime-summary",
                    ),
                ),
            ),
        ),
        "preview-a",
    )
    record = arguments["projections"][0]
    assert record["producer"] == str(_projection().producer)
    assert record["runtimeCellId"] == "runtime-summary"
    assert record["dependencyClosure"] == [
        {
            "cellRef": str(_projection().producer),
            "runtimeCellId": "runtime-summary",
        }
    ]
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
import sys
from marimo_studio._compat.kernel_values.authorization import (
    verify_value_ownership_arguments,
)

arguments = json.load(sys.stdin)
authorized, _active = verify_value_ownership_arguments(
    revision=arguments["revision"],
    projections=arguments["projections"],
    active_projections=arguments["active_projections"],
    consumer_id=arguments["consumer_id"],
    authorization=arguments["authorization"],
)
json.dump(
    {
        "selectors": {
            target: selector.source for target, selector in authorized.selectors.items()
        },
        "bindings": {
            target: [str(binding.producer), binding.runtime_cell_id]
            for target, binding in authorized.bindings.items()
        },
    },
    sys.stdout,
)
""",
        ],
        input=json.dumps(arguments),
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {
        "selectors": {"summary.total": "summary.total"},
        "bindings": {"summary.total": [str(_projection().producer), "runtime-summary"]},
    }


def test_output_accept_lists_are_covered_by_the_server_signature() -> None:
    bound = _bound_with_upstream("output")
    accepting = BoundProjection(
        replace(bound.projection, accept=("image/svg+xml", "image/png")),
        bound.dependency_bindings,
    )
    arguments = authorized_output_arguments(
        "revision-1", (accepting,), (accepting,), "preview-a"
    )
    tampered = json.loads(json.dumps(arguments))
    tampered["projections"][0]["accept"] = ["text/html"]

    authorized, _active = verify_output_arguments(
        revision=arguments["revision"],
        projections=arguments["projections"],
        active_projections=arguments["active_projections"],
        consumer_id=arguments["consumer_id"],
        authorization=arguments["authorization"],
    )
    with pytest.raises(ProjectionAuthorizationError, match="authorization"):
        verify_output_arguments(
            revision=tampered["revision"],
            projections=tampered["projections"],
            active_projections=tampered["active_projections"],
            consumer_id=tampered["consumer_id"],
            authorization=tampered["authorization"],
        )

    assert authorized.accept == {"summary.total": ("image/svg+xml", "image/png")}


def test_output_sizes_are_covered_by_the_server_signature() -> None:
    bound = _bound_with_upstream("output")
    sized = BoundProjection(
        replace(bound.projection, accept=("application/pdf",), size=Size(250.38)),
        bound.dependency_bindings,
    )
    arguments = authorized_output_arguments("revision-1", (sized,), (sized,), "doc")
    tampered = json.loads(json.dumps(arguments))
    tampered["projections"][0]["size"] = {"width": 3_600, "height": 3_600}

    authorized, _active = verify_output_arguments(
        revision=arguments["revision"],
        projections=arguments["projections"],
        active_projections=arguments["active_projections"],
        consumer_id=arguments["consumer_id"],
        authorization=arguments["authorization"],
    )
    with pytest.raises(ProjectionAuthorizationError, match="authorization"):
        verify_output_arguments(
            revision=tampered["revision"],
            projections=tampered["projections"],
            active_projections=tampered["active_projections"],
            consumer_id=tampered["consumer_id"],
            authorization=tampered["authorization"],
        )

    assert authorized.sizes == {"summary.total": Size(250.38)}


@pytest.mark.parametrize(
    ("kind", "accept", "size"),
    (
        ("value", ["image/png"], None),
        ("value", ["application/json"], {"width": 200, "height": None}),
        ("output", [], {"width": 200, "height": None}),
        ("output", ["application/pdf"], {"width": 0, "height": None}),
    ),
)
def test_records_read_values_as_json_and_size_only_accepting_outputs(
    kind: Literal["value", "output"], accept: list[str], size: object
) -> None:
    bound = _bound_with_upstream(kind)
    arguments = (
        authorized_value_arguments("revision-1", (bound,), "doc")
        if kind == "value"
        else authorized_output_arguments("revision-1", (bound,), (bound,), "doc")
    )
    records = cast(list[dict[str, object]], arguments["projections"])
    active = cast(list[dict[str, object]], arguments["active_projections"])
    for record in (*records, *active):
        record["accept"] = accept
        record["size"] = size
    verify = (
        verify_value_ownership_arguments if kind == "value" else verify_output_arguments
    )

    with pytest.raises(ProjectionAuthorizationError, match=r"accept list|size"):
        verify(
            revision=arguments["revision"],
            projections=arguments["projections"],
            active_projections=arguments["active_projections"],
            consumer_id=arguments["consumer_id"],
            authorization=arguments["authorization"],
        )


def test_document_value_records_read_tables_as_json() -> None:
    bound = _bound_with_upstream()
    document = BoundProjection(
        replace(bound.projection, accept=("application/json",)),
        bound.dependency_bindings,
    )
    arguments = authorized_value_arguments("revision-1", (document,), "document")

    authorized, _active = verify_value_ownership_arguments(
        revision=arguments["revision"],
        projections=arguments["projections"],
        active_projections=arguments["active_projections"],
        consumer_id=arguments["consumer_id"],
        authorization=arguments["authorization"],
    )

    assert authorized.accept == {"summary.total": ("application/json",)}


def test_dependency_closure_is_covered_by_the_server_signature() -> None:
    arguments = authorized_value_arguments(
        "revision-1",
        (_bound_with_upstream(),),
        "preview-a",
    )
    tampered = json.loads(json.dumps(arguments))
    tampered["projections"][0]["dependencyClosure"][0]["runtimeCellId"] = (
        "runtime-forged"
    )

    with pytest.raises(ProjectionAuthorizationError, match="authorization"):
        verify_value_ownership_arguments(
            revision=tampered["revision"],
            projections=tampered["projections"],
            active_projections=tampered["active_projections"],
            consumer_id=tampered["consumer_id"],
            authorization=tampered["authorization"],
        )


def test_value_consumer_is_covered_by_the_server_signature() -> None:
    arguments = authorized_value_arguments(
        "revision-1",
        (_bound_with_upstream(),),
        "preview-a",
    )

    with pytest.raises(ProjectionAuthorizationError, match="authorization"):
        verify_value_ownership_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            active_projections=arguments["active_projections"],
            consumer_id="preview-b",
            authorization=arguments["authorization"],
        )


def test_active_value_owners_are_covered_by_the_server_signature() -> None:
    arguments = authorized_value_arguments(
        "revision-1",
        (_bound_with_upstream(),),
        "preview-a",
    )
    arguments["active_projections"] = []

    with pytest.raises(ProjectionAuthorizationError, match="authorization"):
        verify_value_ownership_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            active_projections=arguments["active_projections"],
            consumer_id=arguments["consumer_id"],
            authorization=arguments["authorization"],
        )


@pytest.mark.parametrize("kind", ["cell", "value", "output"])
@pytest.mark.parametrize(
    ("unrelated_id", "draft", "executed"),
    [
        ("runtime-unrelated", "unrelated = 1", "unrelated = 2"),
        ("runtime-draft", "draft = (", "draft = ("),
    ],
    ids=["edited-cell", "syntax-error"],
)
def test_live_binding_accepts_code_changes_with_the_same_runtime_topology(
    kind: Literal["cell", "value", "output"],
    unrelated_id: str,
    draft: str,
    executed: str,
) -> None:
    projection, cells = _projection_with_upstream(kind)
    rows = [
        SimpleNamespace(id=runtime_id, code=code) for _ref, runtime_id, code in cells
    ]
    rows.append(SimpleNamespace(id=unrelated_id, code=draft))
    executed_code = {row.id: row.code for row in rows}
    session = SimpleNamespace(
        document=SimpleNamespace(cells=rows),
        session_view=SimpleNamespace(last_executed_code=executed_code),
    )
    runtime_cell_refs = {ref: runtime_id for ref, runtime_id, _code in cells}

    executed_code[unrelated_id] = executed
    (bound,) = _bind_projections(
        _build_live_projection_state(_executed_signature(session)),
        (projection,),
        runtime_cell_refs,
    )

    assert tuple(
        (binding.cell_ref, binding.runtime_cell_id)
        for binding in bound.dependency_bindings
    ) == tuple((ref, runtime_id) for ref, runtime_id, _code in cells)
    executed_code["runtime-upstream"] = "source = 2"
    (edited,) = _bind_projections(
        _build_live_projection_state(_executed_signature(session)),
        (projection,),
        runtime_cell_refs,
    )
    assert tuple(binding.runtime_cell_id for binding in edited.dependency_bindings) == (
        "runtime-upstream",
        "runtime-summary",
    )


@pytest.mark.parametrize("kind", ["cell", "value", "output"])
def test_live_binding_rejects_a_newly_resolved_upstream_producer(
    kind: Literal["cell", "value", "output"],
) -> None:
    projection, producer_code = _projection_with_unresolved_reference(kind)
    rows = [
        SimpleNamespace(id="runtime-summary", code=producer_code),
        SimpleNamespace(id="runtime-missing", code="missing = 2"),
    ]
    session = SimpleNamespace(
        document=SimpleNamespace(cells=rows),
        session_view=SimpleNamespace(
            last_executed_code={row.id: row.code for row in rows}
        ),
    )

    with pytest.raises(ProjectionUnavailable, match="dependency closure"):
        _bind_projections(
            _build_live_projection_state(_executed_signature(session)),
            (projection,),
            {projection.producer: "runtime-summary"},
        )


@pytest.mark.parametrize("kind", ["value", "output"])
def test_kernel_accepts_a_server_authorized_edit_with_the_same_closure(
    kind: Literal["value", "output"],
) -> None:
    bound = _bound_with_upstream(kind)
    cells = {
        binding.runtime_cell_id: SimpleNamespace(
            code=(
                "source = 1"
                if binding.runtime_cell_id == "runtime-upstream"
                else "summary = {'total': source}"
            ),
            defs={
                "source" if binding.runtime_cell_id == "runtime-upstream" else "summary"
            },
        )
        for binding in bound.dependency_bindings
    }
    graph = _Graph(cells, {"runtime-summary": {"runtime-upstream"}})
    context = SimpleNamespace(_kernel=SimpleNamespace(graph=graph))
    authorized = _verify_bound_projection(kind, bound, revision="revision-1")

    assert _current_selectors(context, authorized)["summary.total"].root == "summary"
    cells["runtime-upstream"].code = "source = 2"
    assert _current_selectors(context, authorized)["summary.total"].root == "summary"

    cells["runtime-upstream"].code = "source = 1"
    cells["runtime-unrelated"] = SimpleNamespace(
        code="unrelated = 2",
        defs={"unrelated"},
    )
    assert _current_selectors(context, authorized)["summary.total"].root == "summary"


@pytest.mark.parametrize("kind", ["value", "output"])
def test_kernel_accepts_a_live_closure_after_graph_reinsertion(
    kind: Literal["value", "output"],
) -> None:
    bound = _bound_with_upstream(kind)
    by_runtime_id = {
        binding.runtime_cell_id: binding for binding in bound.dependency_bindings
    }
    cells = {
        "runtime-summary": SimpleNamespace(
            code="summary = {'total': source}",
            defs={"summary"},
        ),
        "runtime-upstream": SimpleNamespace(
            code="source = 1",
            defs={"source"},
        ),
    }
    graph = _Graph(cells, {"runtime-summary": {"runtime-upstream"}})
    context = SimpleNamespace(_kernel=SimpleNamespace(graph=graph))
    rebound = BoundProjection(
        bound.projection,
        (
            by_runtime_id["runtime-upstream"],
            by_runtime_id["runtime-summary"],
        ),
    )
    authorized = _verify_bound_projection(kind, rebound, revision="revision-2")

    assert _current_selectors(context, authorized)["summary.total"].root == "summary"


@pytest.mark.parametrize("kind", ["value", "output"])
def test_kernel_rejects_a_new_producer_after_capability_binding(
    kind: Literal["value", "output"],
) -> None:
    projection, producer_code = _projection_with_unresolved_reference(kind)
    bound = BoundProjection(
        projection,
        (RuntimeCellBinding(projection.producer, "runtime-summary"),),
    )
    cells = {"runtime-summary": SimpleNamespace(code=producer_code, defs={"summary"})}
    graph = _Graph(cells)
    context = SimpleNamespace(_kernel=SimpleNamespace(graph=graph))
    authorized = _verify_bound_projection(kind, bound, revision="revision-1")

    assert _current_selectors(context, authorized)["summary"].root == "summary"
    cells["runtime-missing"] = SimpleNamespace(
        code="missing = 2",
        defs={"missing"},
    )
    graph.parents["runtime-summary"] = {"runtime-missing"}
    with pytest.raises(ProjectionAuthorizationError, match="dependency closure"):
        _current_selectors(context, authorized)


@pytest.mark.parametrize(
    "changes_during_build",
    [False, True],
    ids=["after-read", "during-build"],
)
def test_projection_host_revalidates_changed_execution_before_invoking_the_kernel(
    monkeypatch: pytest.MonkeyPatch,
    changes_during_build: bool,
) -> None:
    session = _SummarySession()
    original = projection_host._build_live_projection_state
    builds: list[Any] = []
    reads: list[str] = []
    pulse = Event()
    loop: asyncio.AbstractEventLoop | None = None

    def change() -> None:
        session.session_view.last_executed_code["runtime-summary"] = "moved = 3"
        pulse.set()

    def build(signature: Any) -> Any:
        builds.append(signature)
        if changes_during_build and len(builds) == 1:
            assert loop is not None
            loop.call_soon_threadsafe(change)
            assert pulse.wait(1)
        return original(signature)

    async def read(*_args: Any, **_kwargs: Any) -> ValueReadResult:
        reads.append("read")
        return ValueReadResult({}, {})

    host = _install_projection_host(monkeypatch, session, build, read=read)

    async def exercise() -> None:
        nonlocal loop
        loop = asyncio.get_running_loop()
        if not changes_during_build:
            await _live(host, "read_values")
            await _live(host, "read_values")
            assert len(builds) == 1
            assert reads == ["read", "read"]
            change()
        with pytest.raises(ProjectionUnavailable) as raised:
            await _live(host, "read_values")
        assert raised.value.code == "stale-projection-binding"
        assert len(builds) == 2
        assert reads == ([] if changes_during_build else ["read", "read"])

    asyncio.run(exercise())


def test_value_ownership_keeps_requested_and_mounted_selectors_separate() -> None:
    requested = _bound_with_upstream()
    mounted = replace(
        requested,
        projection=replace(
            requested.projection,
            request=replace(requested.projection.request, target="summary"),
            selector=ValueSelector("summary"),
        ),
    )
    arguments = authorized_value_arguments(
        "revision-1", (requested,), "preview-a", (requested, mounted)
    )
    authorized, active = verify_value_ownership_arguments(
        revision=arguments["revision"],
        projections=arguments["projections"],
        active_projections=arguments["active_projections"],
        consumer_id=arguments["consumer_id"],
        authorization=arguments["authorization"],
    )
    assert set(authorized.selectors) == {"summary.total"}
    assert set(active.selectors) == {"summary.total", "summary"}


@pytest.mark.parametrize("transition", ["current", "edited", "cancelled", "failed"])
def test_concurrent_projection_requests_share_session_graph_builds(
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    session = _SummarySession()
    started, release = Event(), Event()
    original = projection_host._build_live_projection_state
    builds: list[Any] = []

    def build(signature: Any) -> Any:
        builds.append(signature)
        if len(builds) == 1:
            started.set()
            assert release.wait(5)
            if transition == "failed":
                raise RuntimeError("graph compilation failed")
        return original(signature)

    host = _install_projection_host(monkeypatch, session, build)

    async def exercise() -> None:
        first = asyncio.create_task(_live(host, "read_values"))
        second: asyncio.Task[Any] | None = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            second = asyncio.create_task(_live(host, "render_outputs"))
            await asyncio.sleep(0)
            if transition == "edited":
                session.session_view.last_executed_code["runtime-summary"] = (
                    "summary = {'total': 4}"
                )
            elif transition == "cancelled":
                first.cancel()
                await asyncio.sleep(0)
                first.cancel()
                await asyncio.sleep(0)
                assert not first.done()
            release.set()
            if transition == "cancelled":
                with pytest.raises(asyncio.CancelledError):
                    await first
            elif transition == "failed":
                with pytest.raises(RuntimeError, match="graph compilation failed"):
                    await first
            else:
                assert isinstance(await first, ValueReadResult)
            assert isinstance(await second, OutputRenderResult)
            assert isinstance(
                await _live(host, "read_values"),
                ValueReadResult,
            )
            assert len(builds) == (2 if transition in {"edited", "failed"} else 1)
            if transition == "edited":
                assert builds[1] == (("runtime-summary", "summary = {'total': 4}"),)
        finally:
            release.set()
            pending = [first] if second is None else [first, second]
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(exercise())


def test_a_projection_build_keeps_other_sessions_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = {
        "first": _SummarySession("summary = {'total': 3}"),
        "second": _SummarySession("summary = {'total': 4}"),
    }
    started, release = Event(), Event()
    original = projection_host._build_live_projection_state

    def build(signature: Any) -> Any:
        if signature == (("runtime-summary", "summary = {'total': 3}"),):
            started.set()
            assert release.wait(5)
        return original(signature)

    host = _install_projection_host(
        monkeypatch,
        sessions["first"],
        build,
        current_session=lambda _context, key: sessions[key],
    )

    async def exercise() -> None:
        first = asyncio.create_task(_live(host, "read_values", "first"))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            second = await asyncio.wait_for(
                _live(host, "read_values", "second"),
                2,
            )
            assert isinstance(second, ValueReadResult)
            assert not first.done()
            release.set()
            assert isinstance(await first, ValueReadResult)
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)

    asyncio.run(exercise())
