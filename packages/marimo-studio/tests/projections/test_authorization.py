"""Protect projection capability authorization."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from marimo_studio._compat.kernel_values.authorization import (
    BoundProjection,
    ProjectionAuthorizationError,
    RuntimeCellBinding,
    authorized_output_arguments,
    authorized_value_arguments,
    verify_output_arguments,
    verify_value_arguments,
)
from marimo_studio._compat.kernel_values.authorization_key import (
    initialize_projection_authorization_key,
    projection_authorization_key,
)
from marimo_studio._compat.kernel_values.host import _bind_live_projections
from marimo_studio._compat.kernel_values.kernel import _current_projection_specs
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ResolvedProjection,
)
from marimo_studio._projections.values import parse_value_reference
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio.view_providers import SourceLocation


def _projection() -> ResolvedProjection:
    reference = parse_value_reference("summary.total")
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
        variable=reference.variable,
        selector_path=reference.path,
        dependency_closure=(producer,),
    )


def _projection_with_upstream(
    kind: Literal["cell", "value", "output"] = "value",
) -> tuple[ResolvedProjection, tuple[tuple[CellRef, str, str], ...]]:
    upstream_code = "source = 1"
    producer_code = "summary = {'total': source}"
    upstream, producer = cell_refs((upstream_code, producer_code))
    reference = parse_value_reference("summary.total")
    projection = ResolvedProjection(
        request=ProjectionRequest(
            site_id=f"site:{kind}:summary",
            instance_id=f"projection-{kind}-summary",
            target="summary" if kind == "cell" else "summary.total",
        ),
        kind=kind,
        source=SourceLocation(PurePosixPath("src/App.tsx"), 2, 3),
        producer=producer,
        variable=None if kind == "cell" else reference.variable,
        selector_path=() if kind == "cell" else reference.path,
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


def _projection_with_unresolved_reference(
    kind: Literal["cell", "value", "output"],
) -> tuple[ResolvedProjection, str]:
    producer_code = "summary = missing"
    producer = cell_refs((producer_code,))[0]
    reference = parse_value_reference("summary")
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
            variable=None if kind == "cell" else reference.variable,
            selector_path=(),
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
from marimo_studio._compat.kernel_values.authorization import verify_value_arguments

arguments = json.load(sys.stdin)
authorized = verify_value_arguments(
    revision=arguments["revision"],
    projections=arguments["projections"],
    authorization=arguments["authorization"],
)
json.dump(
    {
        "specifications": authorized.specifications,
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
        "specifications": {"summary.total": ["summary", [["attribute", "total"]]]},
        "bindings": {"summary.total": [str(_projection().producer), "runtime-summary"]},
    }


def test_dependency_closure_is_covered_by_the_server_signature() -> None:
    arguments = authorized_value_arguments(
        "revision-1",
        (_bound_with_upstream(),),
    )
    tampered = json.loads(json.dumps(arguments))
    tampered["projections"][0]["dependencyClosure"][0]["runtimeCellId"] = (
        "runtime-forged"
    )

    with pytest.raises(ProjectionAuthorizationError, match="authorization"):
        verify_value_arguments(
            revision=tampered["revision"],
            projections=tampered["projections"],
            authorization=tampered["authorization"],
        )


@pytest.mark.parametrize("kind", ["cell", "value", "output"])
def test_live_binding_accepts_code_changes_with_the_same_runtime_topology(
    kind: Literal["cell", "value", "output"],
) -> None:
    projection, cells = _projection_with_upstream(kind)
    rows = [
        SimpleNamespace(id=runtime_id, code=code) for _ref, runtime_id, code in cells
    ]
    rows.append(SimpleNamespace(id="runtime-unrelated", code="unrelated = 1"))
    executed_code = {row.id: row.code for row in rows}
    session = SimpleNamespace(
        document=SimpleNamespace(cells=rows),
        session_view=SimpleNamespace(last_executed_code=executed_code),
    )
    runtime_cell_refs = {ref: runtime_id for ref, runtime_id, _code in cells}

    executed_code["runtime-unrelated"] = "unrelated = 2"
    (bound,) = _bind_live_projections(
        session,
        (projection,),
        runtime_cell_refs,
    )

    assert tuple(
        (binding.cell_ref, binding.runtime_cell_id)
        for binding in bound.dependency_bindings
    ) == tuple((ref, runtime_id) for ref, runtime_id, _code in cells)
    executed_code["runtime-upstream"] = "source = 2"
    (edited,) = _bind_live_projections(
        session,
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
        _bind_live_projections(
            session,
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
    if kind == "value":
        arguments = authorized_value_arguments("revision-1", (bound,))
        authorized = verify_value_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            authorization=arguments["authorization"],
        )
    else:
        arguments = authorized_output_arguments(
            "revision-1",
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

    assert _current_projection_specs(context, authorized)["summary.total"][0] == (
        "summary"
    )
    cells["runtime-upstream"].code = "source = 2"
    assert _current_projection_specs(context, authorized)["summary.total"][0] == (
        "summary"
    )

    cells["runtime-upstream"].code = "source = 1"
    cells["runtime-unrelated"] = SimpleNamespace(
        code="unrelated = 2",
        defs={"unrelated"},
    )
    assert _current_projection_specs(context, authorized)["summary.total"][0] == (
        "summary"
    )


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
    if kind == "value":
        arguments = authorized_value_arguments("revision-2", (rebound,))
        authorized = verify_value_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            authorization=arguments["authorization"],
        )
    else:
        arguments = authorized_output_arguments(
            "revision-2",
            (rebound,),
            (rebound,),
            "preview-a",
        )
        authorized, _active = verify_output_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            active_projections=arguments["active_projections"],
            consumer_id=arguments["consumer_id"],
            authorization=arguments["authorization"],
        )

    assert _current_projection_specs(context, authorized)["summary.total"][0] == (
        "summary"
    )


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
    if kind == "value":
        arguments = authorized_value_arguments("revision-1", (bound,))
        authorized = verify_value_arguments(
            revision=arguments["revision"],
            projections=arguments["projections"],
            authorization=arguments["authorization"],
        )
    else:
        arguments = authorized_output_arguments(
            "revision-1",
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

    assert _current_projection_specs(context, authorized)["summary"][0] == "summary"
    cells["runtime-missing"] = SimpleNamespace(
        code="missing = 2",
        defs={"missing"},
    )
    graph.parents["runtime-summary"] = {"runtime-missing"}
    with pytest.raises(ProjectionAuthorizationError, match="dependency closure"):
        _current_projection_specs(context, authorized)
