"""Describe projection compatibility with Studio static runtimes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, TypeAlias

from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectionKind,
    SourceLocation,
)

StaticRuntime: TypeAlias = Literal["zero-python", "wasm"]
PortabilityStatus: TypeAlias = Literal[
    "supported",
    "verification-required",
    "verified",
    "incompatible",
]


@dataclass(frozen=True, slots=True)
class ProjectionPortability:
    """Describe one projection target against a selected static runtime."""

    site_id: str
    projection: ProjectionKind
    target: str | None
    runtime: StaticRuntime
    status: PortabilityStatus
    source: SourceLocation
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "projection": self.projection,
            "target": self.target,
            "runtime": self.runtime,
            "status": self.status,
            "source": self.source.to_dict(),
            "reason": self.reason,
        }


def projection_portability(
    mounts: tuple[MountDeclaration, ...],
    runtime: StaticRuntime,
) -> tuple[ProjectionPortability, ...]:
    """Describe every authored projection site for one static runtime."""
    results: list[ProjectionPortability] = []
    for site in sorted(mounts, key=lambda item: item.id):
        targets = site.allowed_targets
        if targets is None:
            status: PortabilityStatus = (
                "incompatible" if runtime == "zero-python" else "supported"
            )
            reason = (
                "Zero-Python requires a finite authored target set."
                if runtime == "zero-python"
                else "WebAssembly resolves this target while the notebook runs."
            )
            results.append(
                ProjectionPortability(
                    site.id,
                    site.kind,
                    None,
                    runtime,
                    status,
                    site.source,
                    reason,
                )
            )
            continue
        for target in targets:
            if runtime == "wasm":
                status = "supported"
                reason = "WebAssembly executes the notebook in the browser."
            else:
                status = "verification-required"
                reason = "Zero-Python must capture this projection in every state."
            results.append(
                ProjectionPortability(
                    site.id,
                    site.kind,
                    target,
                    runtime,
                    status,
                    site.source,
                    reason,
                )
            )
    return tuple(results)


def verify_projection_portability(
    projections: tuple[ProjectionPortability, ...],
) -> tuple[ProjectionPortability, ...]:
    """Mark successfully prepared Zero-Python projections as verified."""
    return tuple(
        replace(
            item,
            status="verified",
            reason="Zero-Python prepared this projection successfully.",
        )
        if item.status == "verification-required"
        else item
        for item in projections
    )


__all__ = [
    "PortabilityStatus",
    "ProjectionPortability",
    "StaticRuntime",
    "projection_portability",
    "verify_projection_portability",
]
