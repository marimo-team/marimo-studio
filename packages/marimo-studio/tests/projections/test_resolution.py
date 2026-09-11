"""Protect symbolic projection resolution."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

import pytest

from marimo_studio._notebook.inspection import inspect_notebook
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ProjectionResolutionError,
    projection_policy,
    projection_targets,
    resolve_projection,
)
from marimo_studio._projections.symbol_graph import build_notebook_symbol_graph
from marimo_studio._projections.values import (
    MAX_VALUE_PATH_STEPS,
    MAX_VALUE_REFERENCE_BYTES,
    parse_value_reference,
)
from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectionKind,
    SourceLocation,
)


def _site(
    site_id: str,
    kind: ProjectionKind,
    allowed_targets: tuple[str, ...] | None,
) -> MountDeclaration:
    return MountDeclaration(
        id=site_id,
        kind=kind,
        source=SourceLocation(PurePosixPath("src/App.tsx"), 12, 7),
        allowed_targets=allowed_targets,
    )


def _request(site: MountDeclaration, target: str, instance: str = "instance-1"):
    return ProjectionRequest(
        site_id=site.id,
        instance_id=instance,
        target=target,
    )


def test_bounded_and_wildcard_mounts_share_one_resolver(
    notebook_path: Path,
) -> None:
    notebook = inspect_notebook(notebook_path)
    first, second = notebook.cells
    graph = build_notebook_symbol_graph(
        notebook,
        {"inputs": first, "summary": second},
    )
    literal = _site(
        "site-cell",
        "cell",
        ("summary",),
    )
    bounded = _site(
        "site-values",
        "value",
        ("x", "doubled.real"),
    )
    dynamic = _site(
        "site-dynamic",
        "output",
        None,
    )
    sites = (literal, bounded, dynamic)

    cell = resolve_projection(graph, sites, _request(literal, "summary"))
    value = resolve_projection(graph, sites, _request(bounded, "doubled.real"))
    output = resolve_projection(graph, sites, _request(dynamic, "x"))

    assert cell.producer == second.ref
    assert cell.dependency_closure == (first.ref, second.ref)
    assert value.producer == second.ref
    assert value.selector_spec() == ("doubled", (("attribute", "real"),))
    assert output.producer == first.ref


def test_repeated_literal_sites_resolve_without_static_owner_rejection(
    notebook_path: Path,
) -> None:
    notebook = inspect_notebook(notebook_path)
    graph = build_notebook_symbol_graph(notebook, {"summary": notebook.cells[1]})
    first = _site(
        "site-first",
        "cell",
        ("summary",),
    )
    second = _site(
        "site-second",
        "cell",
        ("summary",),
    )

    assert resolve_projection(graph, (first, second), _request(first, "summary"))
    assert resolve_projection(
        graph,
        (first, second),
        _request(second, "summary", "instance-2"),
    )


@pytest.mark.parametrize(
    ("allowed_targets", "target", "code"),
    [
        (
            ("summary",),
            "inputs",
            "projection-target-not-allowed",
        ),
        (
            None,
            "missing",
            "projection-cell-not-found",
        ),
    ],
)
def test_resolution_rejects_targets_outside_the_site_or_graph(
    notebook_path: Path,
    allowed_targets: tuple[str, ...] | None,
    target: str,
    code: str,
) -> None:
    notebook = inspect_notebook(notebook_path)
    graph = build_notebook_symbol_graph(
        notebook,
        {"inputs": notebook.cells[0], "summary": notebook.cells[1]},
    )
    site = _site("site-cell", "cell", allowed_targets)

    with pytest.raises(ProjectionResolutionError) as captured:
        resolve_projection(graph, (site,), _request(site, target))

    assert captured.value.code == code


def test_selector_bounds_are_published_as_projection_policy(
    notebook_path: Path,
) -> None:
    maximum = "x" + ".a" * MAX_VALUE_PATH_STEPS
    assert len(parse_value_reference(maximum).path) == 64
    with pytest.raises(ValueError, match="path steps"):
        parse_value_reference(maximum + ".a")
    with pytest.raises(ValueError, match="byte limit"):
        parse_value_reference("x" * (MAX_VALUE_REFERENCE_BYTES + 1))
    with pytest.raises(ValueError, match="safe integers"):
        parse_value_reference("x[9007199254740992]")

    notebook = inspect_notebook(notebook_path)
    graph = build_notebook_symbol_graph(notebook, {})
    site = _site(
        "site-value",
        "value",
        None,
    )
    accepted = resolve_projection(
        graph,
        (site,),
        _request(site, "doubled" + ".value" * 64),
    )
    assert len(accepted.selector_path) == 64
    with pytest.raises(ProjectionResolutionError) as rejected:
        resolve_projection(
            graph,
            (site,),
            _request(site, "doubled" + ".value" * 65),
        )
    assert rejected.value.code == "projection-target-invalid"

    assert projection_policy() == {
        "maxActiveInstances": 512,
        "maxUniqueCellTargets": 256,
        "maxUniqueOutputTargets": 100,
        "maxUniqueValueTargets": 100,
        "maxTargetBytes": 4_096,
        "maxPathSteps": 64,
        "maxInstanceIdBytes": 256,
    }


def test_empty_projection_targets_resolve_as_source_site_failures(
    notebook_path: Path,
) -> None:
    notebook = inspect_notebook(notebook_path)
    graph = build_notebook_symbol_graph(notebook, {})
    site = _site(
        "site-dynamic-value",
        "value",
        None,
    )

    with pytest.raises(ProjectionResolutionError) as captured:
        resolve_projection(graph, (site,), _request(site, ""))

    assert captured.value.code == "projection-target-empty"

    missing_site = ProjectionRequest(
        site_id="",
        instance_id="instance-missing-site",
        target="x",
    )
    with pytest.raises(ProjectionResolutionError) as missing:
        resolve_projection(graph, (site,), missing_site)
    assert missing.value.code == "projection-site-not-found"


@pytest.mark.parametrize("kind", ("cell", "value", "output"))
def test_wildcard_projection_targets_require_canonical_text(
    notebook_path: Path,
    kind: ProjectionKind,
) -> None:
    notebook = inspect_notebook(notebook_path)
    graph = build_notebook_symbol_graph(notebook, {"summary": notebook.cells[1]})
    site = _site(f"site-{kind}", kind, None)

    with pytest.raises(ProjectionResolutionError) as captured:
        resolve_projection(graph, (site,), _request(site, " summary "))

    assert captured.value.code == "projection-target-invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    (("target", "\ud800"), ("instance_id", "\udfff")),
)
def test_projection_identifiers_reject_unpaired_utf16_surrogates(
    value: str,
    field: Literal["target", "instance_id"],
) -> None:
    with pytest.raises(ProjectionResolutionError) as captured:
        ProjectionRequest(
            site_id="site:value:dynamic",
            instance_id=value if field == "instance_id" else "projection-1",
            target=value if field == "target" else "summary",
        )

    assert captured.value.code == "projection-unpaired-surrogate"


def test_projection_identifiers_normalize_valid_utf16_surrogate_pairs() -> None:
    request = ProjectionRequest(
        site_id="site:value:dynamic",
        instance_id="projection-\ud83d\ude00",
        target='summary["\ud83d\ude00"]',
    )

    assert request.instance_id == "projection-😀"
    assert request.target == 'summary["😀"]'


@pytest.mark.parametrize(
    "target",
    [r'doubled["\ud800"]', r'doubled["\udfff"]'],
)
def test_projection_selectors_reject_escaped_unpaired_surrogates(
    notebook_path: Path,
    target: str,
) -> None:
    notebook = inspect_notebook(notebook_path)
    graph = build_notebook_symbol_graph(notebook, {})
    site = _site(
        "site-value",
        "value",
        None,
    )

    with pytest.raises(ProjectionResolutionError) as captured:
        resolve_projection(graph, (site,), _request(site, target))

    assert captured.value.code == "projection-unpaired-surrogate"


def test_value_targets_identify_the_producer_without_mounting_its_cell(
    notebook_path: Path,
) -> None:
    notebook = inspect_notebook(notebook_path)
    producer = notebook.cells[1]
    graph = build_notebook_symbol_graph(notebook, {"summary": producer})
    targets = projection_targets(graph, (_site("value", "value", ("doubled",)),))
    assert targets["cells"] == {}
    assert targets["variables"] == {
        "doubled": {
            "status": "ready",
            "producer": str(producer.ref),
            "producerLabel": producer.name or "summary",
            "dependencyClosure": [str(cell.ref) for cell in notebook.cells],
        }
    }
