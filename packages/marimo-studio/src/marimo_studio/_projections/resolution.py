"""Authorize one concrete mount request against the saved notebook graph.

Resolution starts from a mount site recorded in the published artifact. It
checks the requested kind, allowed target, selector syntax, and browser-visible
size limits, then requires one unambiguous source cell or variable. The result
includes the upstream cells Marimo must execute before that target is ready.

Missing, ambiguous, disallowed, and oversized requests return stable error
codes before they reach a kernel. Runtime configuration derives target records
and limits from this module, while browser-evidence verification resolves each
observed instance through it.
"""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.records import ValuePathStep, ValueReference
from marimo_studio._projections.symbol_graph import NotebookSymbolGraph
from marimo_studio._projections.values import (
    MAX_VALUE_PATH_STEPS,
    MAX_VALUE_REFERENCE_BYTES,
    UnpairedUTF16SurrogateError,
    normalize_utf16_surrogate_pairs,
    parse_value_reference,
)
from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectionKind,
    SourceLocation,
)
from marimo_studio.view_providers._targets import validate_projection_target

MAX_PROJECTION_INSTANCE_ID_BYTES = 256
MAX_ACTIVE_PROJECTION_INSTANCES = 512
MAX_UNIQUE_CELL_TARGETS = 256
MAX_UNIQUE_OUTPUT_TARGETS = 100
MAX_UNIQUE_VALUE_TARGETS = 100
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
        if len(self.target.encode("utf-8")) > MAX_VALUE_REFERENCE_BYTES:
            raise ProjectionResolutionError(
                "projection-target-too-large",
                f"The projection target exceeds {MAX_VALUE_REFERENCE_BYTES} bytes.",
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
    variable: str | None
    selector_path: tuple[ValuePathStep, ...]
    dependency_closure: tuple[CellRef, ...]

    def selector_spec(self) -> tuple[str, tuple[tuple[str, str | int], ...]]:
        if self.variable is None:
            raise ValueError("Cell projections do not have selector specs")
        return (
            self.variable,
            tuple((step.kind, step.value) for step in self.selector_path),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "siteId": self.request.site_id,
            "instanceId": self.request.instance_id,
            "kind": self.kind,
            "target": self.request.target,
            "source": self.source.to_dict(),
            "producer": str(self.producer),
            "variable": self.variable,
            "selectorPath": [
                {"kind": step.kind, "value": step.value} for step in self.selector_path
            ],
            "dependencyClosure": [str(ref) for ref in self.dependency_closure],
        }


def _site_for(
    sites: tuple[MountDeclaration, ...],
    request: ProjectionRequest,
) -> MountDeclaration:
    matches = tuple(site for site in sites if site.id == request.site_id)
    if len(matches) != 1:
        raise ProjectionResolutionError(
            "projection-site-not-found",
            f"Projection site {request.site_id!r} is unavailable.",
        )
    site = matches[0]
    return site


def _authorize_target(site: MountDeclaration, target: str) -> None:
    if site.allowed_targets is not None and target not in site.allowed_targets:
        raise ProjectionResolutionError(
            "projection-target-not-allowed",
            f"Projection target {target!r} is not allowed by mount {site.id!r}.",
        )


def validate_mount_declaration(site: MountDeclaration) -> None:
    """Validate one provider-owned site before it enters a presentation."""
    targets = site.allowed_targets
    if targets is None:
        return
    if not targets or len(set(targets)) != len(targets):
        raise ProjectionResolutionError(
            "projection-mount-invalid",
            f"Projection mount {site.id!r} has invalid allowed targets.",
        )
    for target in targets:
        if not target or len(target.encode("utf-8")) > MAX_VALUE_REFERENCE_BYTES:
            raise ProjectionResolutionError(
                "projection-mount-invalid",
                f"Projection mount {site.id!r} contains an invalid target.",
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
    sites: tuple[MountDeclaration, ...],
    request: ProjectionRequest,
) -> ResolvedProjection:
    """Resolve one target through its artifact site and notebook graph."""
    site = _site_for(sites, request)
    validate_mount_declaration(site)
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
    reference: ValueReference | None = None
    if site.kind == "cell":
        producer = _unique_ref(
            graph.cell_targets.get(request.target, ()),
            target=request.target,
            missing_code="projection-cell-not-found",
            ambiguous_code="projection-cell-ambiguous",
            noun="Cell target",
        )
    else:
        try:
            reference = parse_value_reference(request.target)
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
        variable = graph.variables.get(reference.variable)
        producer = _unique_ref(
            variable.producers if variable is not None else (),
            target=reference.variable,
            missing_code=f"projection-{site.kind}-variable-not-found",
            ambiguous_code=f"projection-{site.kind}-variable-ambiguous",
            noun="Notebook variable",
        )
    return ResolvedProjection(
        request=request,
        kind=site.kind,
        source=site.source,
        producer=producer,
        variable=reference.variable if reference is not None else None,
        selector_path=reference.path if reference is not None else (),
        dependency_closure=graph.dependency_closure(producer),
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
        "dependencyClosure": [
            str(reference) for reference in graph.dependency_closure(producer)
        ],
    }


def projection_targets(
    graph: NotebookSymbolGraph,
    sites: tuple[MountDeclaration, ...],
) -> dict[str, object]:
    """Return the target records required by one artifact's mount declarations."""
    cell_targets: set[str] = set()
    variable_targets: set[str] = set()
    all_cells = False
    all_variables = False
    for site in sites:
        if site.allowed_targets is None:
            if site.kind == "cell":
                all_cells = True
            else:
                all_variables = True
            continue
        if site.kind == "cell":
            cell_targets.update(site.allowed_targets)
            continue
        for target in site.allowed_targets:
            variable_targets.add(parse_value_reference(target).variable)
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
        "maxTargetBytes": MAX_VALUE_REFERENCE_BYTES,
        "maxPathSteps": MAX_VALUE_PATH_STEPS,
        "maxInstanceIdBytes": MAX_PROJECTION_INSTANCE_ID_BYTES,
    }
