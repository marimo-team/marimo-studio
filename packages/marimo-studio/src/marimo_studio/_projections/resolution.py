"""Authorize one concrete projection request against the saved notebook graph.

Resolution starts from a site recorded in the published artifact. It
checks the requested kind, site target, selector syntax, and browser-visible
size limits, then requires one unambiguous source cell or variable. The result
includes the upstream cells Marimo must execute before that target is ready.

Missing, ambiguous, disallowed, and oversized requests return stable error
codes before they reach a kernel. Runtime configuration derives target records
and limits from this module, while browser-evidence verification resolves each
observed instance through it.
"""

from __future__ import annotations

from dataclasses import dataclass

from marimo_export.values import MAX_SELECTOR_STEPS, ValueSelector

from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.symbol_graph import NotebookSymbolGraph
from marimo_studio.view_providers import (
    ProjectionKind,
    SourceLocation,
)
from marimo_studio.view_providers._artifact_sites import ArtifactSite, media_accept
from marimo_studio.view_providers._targets import (
    MAX_CELL_TARGETS,
    MAX_TARGET_BYTES,
    MAX_VALUE_TARGETS,
    UnpairedUTF16SurrogateError,
    normalize_utf16_surrogate_pairs,
    validate_projection_target,
)

MAX_PROJECTION_INSTANCE_ID_BYTES = 256
MAX_ACTIVE_PROJECTION_INSTANCES = 512
# One page activates at most as many unique targets as one site may declare.
MAX_UNIQUE_CELL_TARGETS = MAX_CELL_TARGETS
MAX_UNIQUE_OUTPUT_TARGETS = MAX_VALUE_TARGETS
MAX_UNIQUE_VALUE_TARGETS = MAX_VALUE_TARGETS
PROJECTION_UNPAIRED_SURROGATE_CODE = "projection-unpaired-surrogate"


class ProjectionResolutionError(ValueError):
    """One projection request cannot resolve inside its presentation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProjectionRequest:
    """One mounted browser host requesting a notebook projection target."""

    site_id: str
    instance_id: str
    target: str

    def __post_init__(self) -> None:
        values = {"projection instance ID": self.instance_id}
        for label, value in values.items():
            if not isinstance(value, str) or not value:
                raise ProjectionResolutionError(
                    "invalid-projection-request",
                    f"The {label} must be a non-empty string.",
                )
        if not isinstance(self.site_id, str):
            raise ProjectionResolutionError(
                "invalid-projection-request",
                "The projection site ID must be a string.",
            )
        if not isinstance(self.target, str):
            raise ProjectionResolutionError(
                "invalid-projection-request",
                "The projection target must be a string.",
            )
        try:
            instance_id = normalize_utf16_surrogate_pairs(self.instance_id)
            target = normalize_utf16_surrogate_pairs(self.target)
        except UnpairedUTF16SurrogateError as error:
            raise ProjectionResolutionError(
                PROJECTION_UNPAIRED_SURROGATE_CODE,
                "Projection targets and instance IDs require well-formed Unicode.",
            ) from error
        object.__setattr__(self, "instance_id", instance_id)
        object.__setattr__(self, "target", target)
        if len(self.instance_id.encode("utf-8")) > MAX_PROJECTION_INSTANCE_ID_BYTES:
            raise ProjectionResolutionError(
                "projection-instance-id-too-large",
                "The projection instance ID exceeds the byte limit.",
            )
        if len(self.target.encode("utf-8")) > MAX_TARGET_BYTES:
            raise ProjectionResolutionError(
                "projection-target-too-large",
                f"The projection target exceeds {MAX_TARGET_BYTES} bytes.",
            )

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> ProjectionRequest:
        if not isinstance(value, dict) or set(value) != {
            "siteId",
            "instanceId",
            "target",
        }:
            raise ProjectionResolutionError(
                "invalid-projection-request",
                "A projection request must contain siteId, instanceId, and target.",
            )
        site_id = value.get("siteId")
        instance_id = value.get("instanceId")
        target = value.get("target")
        if not all(isinstance(item, str) for item in (site_id, instance_id, target)):
            raise ProjectionResolutionError(
                "invalid-projection-request",
                "Projection request identifiers and targets must be strings.",
            )
        assert isinstance(site_id, str)
        assert isinstance(instance_id, str)
        assert isinstance(target, str)
        return cls(
            site_id=site_id,
            instance_id=instance_id,
            target=target,
        )


@dataclass(frozen=True)
class ResolvedProjection:
    """A projection request joined to its stable notebook producer."""

    request: ProjectionRequest
    kind: ProjectionKind
    source: SourceLocation
    producer: CellRef
    selector: ValueSelector | None
    dependency_closure: tuple[CellRef, ...]
    accept: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "siteId": self.request.site_id,
            "instanceId": self.request.instance_id,
            "kind": self.kind,
            "target": self.request.target,
            "source": self.source.to_dict(),
            "producer": str(self.producer),
            "variable": self.selector.root if self.selector is not None else None,
            "selectorPath": [
                {"kind": step.kind, "value": step.key}
                for step in (self.selector.path if self.selector is not None else ())
            ],
            "dependencyClosure": [str(ref) for ref in self.dependency_closure],
        }


def _site_for(
    sites: tuple[ArtifactSite, ...],
    request: ProjectionRequest,
) -> ArtifactSite:
    matches = tuple(site for site in sites if site.id == request.site_id)
    if len(matches) != 1:
        raise ProjectionResolutionError(
            "projection-site-not-found",
            f"Projection site {request.site_id!r} is unavailable.",
        )
    site = matches[0]
    return site


def _authorize_target(site: ArtifactSite, target: str) -> None:
    if site.targets is not None and target not in site.targets:
        raise ProjectionResolutionError(
            "projection-target-not-allowed",
            f"Projection target {target!r} is not allowed by the {site.kind} host "
            f"at {site.source.path}:{site.source.line}:{site.source.column}.",
        )


def validate_artifact_site(site: ArtifactSite) -> None:
    """Validate one provider-owned site before it enters a presentation."""
    targets = site.targets
    if targets is None:
        return
    if not targets or len(set(targets)) != len(targets):
        raise ProjectionResolutionError(
            "projection-site-invalid",
            f"Projection site {site.id!r} has invalid targets.",
        )
    for target in targets:
        if not target or len(target.encode("utf-8")) > MAX_TARGET_BYTES:
            raise ProjectionResolutionError(
                "projection-site-invalid",
                f"Projection site {site.id!r} contains an invalid target.",
            )


def _unique_ref(
    candidates: tuple[CellRef, ...],
    *,
    target: str,
    missing_code: str,
    ambiguous_code: str,
    noun: str,
) -> CellRef:
    if not candidates:
        raise ProjectionResolutionError(
            missing_code,
            f"{noun} {target!r} does not resolve in the notebook.",
        )
    if len(candidates) != 1:
        raise ProjectionResolutionError(
            ambiguous_code,
            f"{noun} {target!r} has multiple notebook producers.",
        )
    return candidates[0]


def resolve_projection(
    graph: NotebookSymbolGraph,
    sites: tuple[ArtifactSite, ...],
    request: ProjectionRequest,
) -> ResolvedProjection:
    """Resolve one target through its artifact site and notebook graph."""
    site = _site_for(sites, request)
    validate_artifact_site(site)
    if not request.target:
        raise ProjectionResolutionError(
            "projection-target-empty",
            "A mounted projection target must not be empty.",
        )
    try:
        validate_projection_target(site.kind, request.target)
    except UnpairedUTF16SurrogateError as error:
        raise ProjectionResolutionError(
            PROJECTION_UNPAIRED_SURROGATE_CODE,
            "Projection targets and instance IDs require well-formed Unicode.",
        ) from error
    except ValueError as error:
        raise ProjectionResolutionError(
            "projection-target-invalid",
            f"Projection target {request.target!r} is invalid: {error}",
        ) from error
    _authorize_target(site, request.target)
    selector: ValueSelector | None = None
    if site.kind == "cell":
        producer = _unique_ref(
            graph.cell_targets.get(request.target, ()),
            target=request.target,
            missing_code="projection-cell-not-found",
            ambiguous_code="projection-cell-ambiguous",
            noun="Cell target",
        )
    else:
        selector = ValueSelector(request.target)
        variable = graph.variables.get(selector.root)
        producer = _unique_ref(
            variable.producers if variable is not None else (),
            target=selector.root,
            missing_code=f"projection-{site.kind}-variable-not-found",
            ambiguous_code=f"projection-{site.kind}-variable-ambiguous",
            noun="Notebook variable",
        )
    return ResolvedProjection(
        request=request,
        kind=site.kind,
        source=site.source,
        producer=producer,
        selector=selector,
        dependency_closure=graph.dependency_closure(producer),
        accept=media_accept(sites, "output").get(request.target, ())
        if site.kind == "output"
        else (),
    )


def _target_record(
    graph: NotebookSymbolGraph,
    candidates: tuple[CellRef, ...],
) -> dict[str, object] | None:
    if not candidates:
        return None
    if len(candidates) > 1:
        return {"status": "ambiguous"}
    producer = next(iter(candidates))
    return {
        "status": "ready",
        "producer": str(producer),
        "producerLabel": (
            graph.cells[producer].name
            or next(iter(graph.cells[producer].aliases), None)
            or f"Cell {graph.cells[producer].index + 1}"
        ),
        "dependencyClosure": [
            str(reference) for reference in graph.dependency_closure(producer)
        ],
    }


def projection_targets(
    graph: NotebookSymbolGraph,
    sites: tuple[ArtifactSite, ...],
) -> dict[str, object]:
    """Return the target records required by one artifact's sites."""
    cell_targets: set[str] = set()
    variable_targets: set[str] = set()
    all_cells = False
    all_variables = False
    for site in sites:
        if site.targets is None:
            if site.kind == "cell":
                all_cells = True
            else:
                all_variables = True
            continue
        if site.kind == "cell":
            cell_targets.update(site.targets)
            continue
        for target in site.targets:
            variable_targets.add(ValueSelector(target).root)
    if all_cells:
        cell_targets.update(graph.cell_targets)
    if all_variables:
        variable_targets.update(graph.variables)

    cells = {
        target: record
        for target in sorted(cell_targets)
        if (record := _target_record(graph, graph.cell_targets.get(target, ())))
        is not None
    }
    variables = {
        target: record
        for target in sorted(variable_targets)
        if (
            record := _target_record(
                graph,
                (
                    graph.variables[target].producers
                    if target in graph.variables
                    else ()
                ),
            )
        )
        is not None
    }
    return {"cells": cells, "variables": variables}


def projection_policy() -> dict[str, int]:
    """Return browser-visible limits enforced by the Python resolver."""
    return {
        "maxActiveInstances": MAX_ACTIVE_PROJECTION_INSTANCES,
        "maxUniqueCellTargets": MAX_UNIQUE_CELL_TARGETS,
        "maxUniqueOutputTargets": MAX_UNIQUE_OUTPUT_TARGETS,
        "maxUniqueValueTargets": MAX_UNIQUE_VALUE_TARGETS,
        "maxTargetBytes": MAX_TARGET_BYTES,
        "maxPathSteps": MAX_SELECTOR_STEPS,
        "maxInstanceIdBytes": MAX_PROJECTION_INSTANCE_ID_BYTES,
    }
