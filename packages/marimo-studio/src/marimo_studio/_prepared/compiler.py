"""Compile finite provider mounts into one marimo-export specification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType

from marimo_export import ExportSpec, OutputSpec, StateSpace

from marimo_studio._notebook.records import CellRef
from marimo_studio._projections.resolution import ProjectionRequest, resolve_projection
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers import MountDeclaration, ProjectionKind

_ProjectionIdentity = tuple[ProjectionKind, str]
_MAX_OUTPUT_NAME_BYTES = 255


def _immutable_bindings(bindings: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted(bindings.items())))


@dataclass(frozen=True, slots=True)
class ViewBindings:
    """Map canonical projection targets to marimo-export output names."""

    cells: Mapping[str, str]
    outputs: Mapping[str, str]
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _immutable_bindings(self.cells))
        object.__setattr__(self, "outputs", _immutable_bindings(self.outputs))
        object.__setattr__(self, "values", _immutable_bindings(self.values))


@dataclass(frozen=True, slots=True)
class CompiledExportView:
    spec: ExportSpec
    bindings: ViewBindings


def _output_name(identity: _ProjectionIdentity) -> str:
    kind, target = identity
    readable = f"{kind}:{target}"
    if len(readable.encode("utf-8")) <= _MAX_OUTPUT_NAME_BYTES and not any(
        ord(character) < 32 or ord(character) == 127 for character in readable
    ):
        return readable
    digest = sha256(f"{kind}\0{target}".encode()).hexdigest()
    return f"{kind}:{digest}"


def _output_spec(
    resolved: ResolvedStudio,
    kind: ProjectionKind,
    target: str,
    producer: CellRef,
) -> OutputSpec:
    if kind == "value":
        return OutputSpec.native(target)
    if kind == "output":
        return OutputSpec.output(target)
    cell = resolved.notebook.by_ref().get(producer)
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
    mounts: tuple[MountDeclaration, ...],
    *,
    state_space: StateSpace | None = None,
) -> CompiledExportView:
    """Compile one immutable mount catalog into finite prepared outputs."""
    if not mounts:
        raise PublicationError(
            "Zero-Python preparation requires at least one projection mount."
        )
    identities: dict[_ProjectionIdentity, OutputSpec] = {}
    for site in sorted(mounts, key=lambda item: item.id):
        if site.allowed_targets is None:
            raise PublicationError(
                f"Projection site {site.id!r} selects targets dynamically. "
                "Declare a finite target set before using Zero-Python."
            )
        for index, target in enumerate(site.allowed_targets):
            projection = resolve_projection(
                resolved.symbols,
                mounts,
                ProjectionRequest(site.id, f"prepared:{site.id}:{index}", target),
            )
            identity = (site.kind, target)
            output = _output_spec(resolved, site.kind, target, projection.producer)
            previous = identities.setdefault(identity, output)
            if previous != output:
                raise PublicationError(
                    f"Projection target {target!r} resolves to conflicting "
                    "notebook outputs."
                )
    names = {identity: _output_name(identity) for identity in identities}
    if len(set(names.values())) != len(names):
        raise RuntimeError("Prepared output identities produced the same name")
    bindings: dict[ProjectionKind, dict[str, str]] = {
        "cell": {},
        "output": {},
        "value": {},
    }
    outputs: dict[str, OutputSpec] = {}
    for identity in sorted(identities):
        name = names[identity]
        outputs[name] = identities[identity]
        bindings[identity[0]][identity[1]] = name
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
            cells=bindings["cell"],
            outputs=bindings["output"],
            values=bindings["value"],
        ),
    )


__all__ = ["CompiledExportView", "ViewBindings", "compile_export_view"]
