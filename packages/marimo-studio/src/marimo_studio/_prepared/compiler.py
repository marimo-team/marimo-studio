"""Compile finite provider sites into one marimo-export specification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType

from marimo_export import ExportSpec, OutputSpec, StateSpace
from marimo_export.exporters import media
from marimo_export.limits import MAX_NAME_BYTES

from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ResolvedProjection,
    resolve_projection,
)
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio._projections.runtime_records import MEDIA_SCALE
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers import ProjectionKind
from marimo_studio.view_providers._artifact_sites import JSON_ACCEPT, ArtifactSite

_ScopedIdentity = tuple[ProjectionKind, str, str]


def _immutable_bindings(bindings: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted(bindings.items())))


@dataclass(frozen=True, slots=True)
class TargetBindings:
    """Map canonical projection targets of one kind to export output names."""

    cells: Mapping[str, str]
    outputs: Mapping[str, str]
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _immutable_bindings(self.cells))
        object.__setattr__(self, "outputs", _immutable_bindings(self.outputs))
        object.__setattr__(self, "values", _immutable_bindings(self.values))

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            "cells": dict(self.cells),
            "outputs": dict(self.outputs),
            "values": dict(self.values),
        }


@dataclass(frozen=True, slots=True)
class ViewBindings:
    """Bind a view's page hosts and each render's reads to export outputs.

    ``renders`` maps each render source to the targets it reads. A render read
    shares the page's output when both read a target in the same form.
    """

    cells: Mapping[str, str]
    outputs: Mapping[str, str]
    values: Mapping[str, str]
    renders: Mapping[str, TargetBindings] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _immutable_bindings(self.cells))
        object.__setattr__(self, "outputs", _immutable_bindings(self.outputs))
        object.__setattr__(self, "values", _immutable_bindings(self.values))
        object.__setattr__(
            self, "renders", MappingProxyType(dict(sorted(self.renders.items())))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "cells": dict(self.cells),
            "outputs": dict(self.outputs),
            "values": dict(self.values),
            "renders": {
                source: bindings.to_dict() for source, bindings in self.renders.items()
            },
        }


@dataclass(frozen=True, slots=True)
class CompiledExportView:
    spec: ExportSpec
    bindings: ViewBindings


def _output_name(kind: str, target: str) -> str:
    readable = f"{kind}:{target}"
    if len(readable.encode("utf-8")) <= MAX_NAME_BYTES and not any(
        ord(character) < 32 or ord(character) == 127 for character in readable
    ):
        return readable
    digest = sha256(f"{kind}\0{target}".encode()).hexdigest()
    return f"{kind}:{digest}"


def _output_spec(
    resolved: ResolvedStudio, projection: ResolvedProjection
) -> OutputSpec:
    target = projection.request.target
    if projection.kind == "value":
        # A render reads JSON, with tables as rows. A page keeps native values,
        # so tables export as Arrow.
        if projection.accept == JSON_ACCEPT:
            return OutputSpec.json(target)
        return OutputSpec.native(target)
    if projection.kind == "output" and projection.accept:
        return OutputSpec.export(
            target,
            media(projection.accept, scale=MEDIA_SCALE, size=projection.size),
        )
    if projection.kind == "output":
        return OutputSpec.output(target)
    cell = resolved.notebook.by_ref().get(projection.producer)
    if cell is None:
        raise PublicationError(
            f"Prepared cell target {target!r} has no notebook producer."
        )
    return (
        OutputSpec.cell(name=cell.name)
        if cell.name is not None
        else OutputSpec.cell(id=cell.runtime_id)
    )


def compile_export_view(
    resolved: ResolvedStudio,
    view_name: str,
    sites: tuple[ArtifactSite, ...],
    *,
    state_space: StateSpace | None = None,
) -> CompiledExportView:
    """Compile one immutable site catalog into finite prepared outputs."""
    if not sites:
        raise PublicationError(
            "The Prepared runtime requires at least one projection site."
        )
    identities: dict[_ScopedIdentity, OutputSpec] = {}
    for site in sorted(sites, key=lambda item: item.id):
        if site.targets is None:
            source = site.source
            raise PublicationError(
                f"The {site.kind} projection at {source.path}:{source.line}:"
                f"{source.column} selects its target at runtime. Declare a finite "
                "target set before using the Prepared runtime."
            )
        for index, target in enumerate(site.targets):
            projection = resolve_projection(
                resolved.symbols,
                sites,
                ProjectionRequest(site.id, f"prepared:{site.id}:{index}", target),
            )
            render = site.render.as_posix() if site.render is not None else ""
            identity = (site.kind, target, render)
            output = _output_spec(resolved, projection)
            previous = identities.setdefault(identity, output)
            if previous != output:
                raise PublicationError(
                    f"Projection target {target!r} resolves to conflicting "
                    "notebook outputs."
                )
    # Reads of one target in the same form share one export output, named by
    # its kind and target. Another form of the target is named by its render.
    names: dict[_ScopedIdentity, str] = {}
    # Exporter options hold dictionaries, so specs compare by equality.
    shared: list[tuple[ProjectionKind, str, OutputSpec, str]] = []
    for identity in sorted(identities, key=lambda item: (item[0], item[1], item[2])):
        kind, target, render = identity
        spec = identities[identity]
        name = next(
            (
                item[3]
                for item in shared
                if item[:2] == (kind, target) and item[2] == spec
            ),
            None,
        )
        if name is None:
            taken = any(item[:2] == (kind, target) for item in shared)
            name = _output_name(
                f"{kind}@{sha256(render.encode()).hexdigest()[:8]}" if taken else kind,
                target,
            )
            shared.append((kind, target, spec, name))
        names[identity] = name
    if len({item[3] for item in shared}) != len(shared):
        raise RuntimeError("Prepared output identities produced the same name")
    page: dict[ProjectionKind, dict[str, str]] = {"cell": {}, "output": {}, "value": {}}
    reads: dict[str, dict[ProjectionKind, dict[str, str]]] = {}
    outputs: dict[str, OutputSpec] = {}
    for identity, name in names.items():
        kind, target, render = identity
        outputs[name] = identities[identity]
        scope = (
            page
            if not render
            else reads.setdefault(render, {"cell": {}, "output": {}, "value": {}})
        )
        scope[kind][target] = name
    selected_states = state_space or StateSpace(
        default_state="baseline",
        states={"baseline": {}},
    )
    return CompiledExportView(
        spec=ExportSpec.from_state_space(
            selected_states,
            outputs=outputs,
        ),
        bindings=ViewBindings(
            cells=page["cell"],
            outputs=page["output"],
            values=page["value"],
            renders={
                render: TargetBindings(
                    cells=bindings["cell"],
                    outputs=bindings["output"],
                    values=bindings["value"],
                )
                for render, bindings in reads.items()
            },
        ),
    )


__all__ = [
    "CompiledExportView",
    "TargetBindings",
    "ViewBindings",
    "compile_export_view",
]
