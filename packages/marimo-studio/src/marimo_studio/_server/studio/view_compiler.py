"""Compile one Studio view into an export specification and host bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Literal, TypeAlias

from marimo_export import ExportSpec, OutputSpec

from marimo_studio._server.presentation import PresentationSnapshot

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
ProjectionKind = Literal["cell", "output", "value"]
_ProjectionIdentity = tuple[ProjectionKind, str]
_MAX_OUTPUT_NAME_BYTES = 255
_MAX_PROJECTION_HOST_BYTES = 1_024


def _immutable_bindings(
    bindings: Mapping[str, str],
) -> Mapping[str, str]:
    return MappingProxyType(
        {_projection_host(host): output for host, output in sorted(bindings.items())}
    )


def _projection_host(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
        or len(value.encode("utf-8")) > _MAX_PROJECTION_HOST_BYTES
    ):
        raise ValueError(
            "projection host must be a Unicode scalar string of at most "
            f"{_MAX_PROJECTION_HOST_BYTES} UTF-8 bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class ViewBindings:
    """Map authored projection hosts to marimo-export output names."""

    cells: Mapping[str, str]
    outputs: Mapping[str, str]
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _immutable_bindings(self.cells))
        object.__setattr__(self, "outputs", _immutable_bindings(self.outputs))
        object.__setattr__(self, "values", _immutable_bindings(self.values))


@dataclass(frozen=True, slots=True)
class CompiledExportView:
    """Pair a notebook export specification with Studio-owned host bindings."""

    spec: ExportSpec
    bindings: ViewBindings


@dataclass(frozen=True, slots=True)
class _Projection:
    kind: ProjectionKind
    host: str
    source: str
    label: str
    output: OutputSpec


def _digest_output_name(kind: ProjectionKind, source: str) -> str:
    identity = f"{kind}\0{source}".encode()
    return f"{kind}:{sha256(identity).hexdigest()}"


def _readable_output_name(kind: ProjectionKind, label: str) -> str | None:
    name = f"{kind}:{label}"
    if (
        name != name.strip()
        or len(name.encode()) > _MAX_OUTPUT_NAME_BYTES
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        return None
    return name


def _projection_names(
    projections: tuple[_Projection, ...],
) -> Mapping[_ProjectionIdentity, str]:
    initial: dict[_ProjectionIdentity, str] = {}
    for projection in projections:
        identity = (projection.kind, projection.source)
        name = _readable_output_name(projection.kind, projection.label)
        initial[identity] = name or _digest_output_name(*identity)
    resolved = _resolve_name_collisions(initial)
    resolved = _resolve_name_collisions(resolved)
    if len(set(resolved.values())) != len(resolved):
        raise RuntimeError("Export output identities produced the same digest")
    return MappingProxyType(resolved)


def _resolve_name_collisions(
    names: Mapping[_ProjectionIdentity, str],
) -> dict[_ProjectionIdentity, str]:
    identities_by_name: dict[str, set[_ProjectionIdentity]] = {}
    for identity, name in names.items():
        identities_by_name.setdefault(name, set()).add(identity)
    collisions = {
        name for name, identities in identities_by_name.items() if len(identities) > 1
    }
    return {
        identity: (_digest_output_name(*identity) if name in collisions else name)
        for identity, name in names.items()
    }


def compile_export_view(
    snapshot: PresentationSnapshot,
    *,
    states: Mapping[str, Mapping[str, JsonValue]] | None = None,
    default_state: str = "baseline",
) -> CompiledExportView:
    """Compile selected outputs and explicit states from one view snapshot."""

    projections: list[_Projection] = []
    for host, reference in sorted(snapshot.value_references.items()):
        projections.append(
            _Projection(
                "value",
                host,
                reference.source,
                reference.source,
                OutputSpec.value(reference.source),
            )
        )
    for host, reference in sorted(snapshot.output_references.items()):
        projections.append(
            _Projection(
                "output",
                host,
                reference.source,
                reference.source,
                OutputSpec.output(reference.source),
            )
        )
    view = snapshot.resolved.views[snapshot.view_name]
    for host in sorted(view.cell_aliases):
        cell = snapshot.resolved.aliases[host]
        if cell.name is None:
            projections.append(
                _Projection(
                    "cell",
                    host,
                    f"id:{cell.runtime_id}",
                    cell.runtime_id,
                    OutputSpec.cell(id=cell.runtime_id),
                )
            )
        else:
            projections.append(
                _Projection(
                    "cell",
                    host,
                    f"name:{cell.name}",
                    cell.name,
                    OutputSpec.cell(name=cell.name),
                )
            )

    export_outputs: dict[str, OutputSpec] = {}
    cells: dict[str, str] = {}
    outputs: dict[str, str] = {}
    values: dict[str, str] = {}
    names = _projection_names(tuple(projections))
    binding_maps = {"cell": cells, "output": outputs, "value": values}
    for projection in projections:
        name = names[(projection.kind, projection.source)]
        export_outputs.setdefault(name, projection.output)
        binding_maps[projection.kind][projection.host] = name

    return CompiledExportView(
        spec=ExportSpec(
            default_state=default_state,
            states={"baseline": {}} if states is None else states,
            outputs=export_outputs,
        ),
        bindings=ViewBindings(cells=cells, outputs=outputs, values=values),
    )


__all__ = ["CompiledExportView", "ViewBindings", "compile_export_view"]
