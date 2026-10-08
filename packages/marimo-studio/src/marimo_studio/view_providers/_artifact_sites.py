"""Derive artifact sites from provider projection sites."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from marimo_studio.view_providers._records import (
    ProjectInspection,
    ProjectionKind,
    ProjectionSite,
    SourceLocation,
)

SITE_ATTRIBUTE = "data-marimo-studio-site"


@dataclass(frozen=True)
class ArtifactSite:
    """One artifact-local projection site with its Studio-assigned identity.

    An output site with ``accept`` reads its target in the first of those media
    types the value supports. Without it, the site reads marimo's native output.
    """

    id: str
    kind: ProjectionKind
    source: SourceLocation
    targets: tuple[str, ...] | None
    accept: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source.to_dict(),
            "targets": (list(self.targets) if self.targets is not None else None),
            "accept": list(self.accept),
        }


def _site_id(*identity: object) -> str:
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return f"site-{hashlib.sha256(encoded.encode()).hexdigest()}"


def artifact_sites(
    sites: tuple[ProjectionSite, ...],
) -> tuple[ArtifactSite, ...]:
    """Assign stable IDs to sites in the order the provider reported them.

    The identity omits the source position, so a host keeps its ID when it
    moves inside its file. Hosts sharing a path, kind, and single target are
    numbered by their position in that file.
    """
    ordered = sorted(
        range(len(sites)),
        key=lambda index: (
            sites[index].source.path.as_posix(),
            sites[index].offset,
        ),
    )
    occurrences: dict[tuple[PurePosixPath, ProjectionKind, str | None], int] = {}
    identities: dict[int, str] = {}
    for index in ordered:
        site = sites[index]
        target = (
            site.targets[0] if site.targets != "*" and len(site.targets) == 1 else None
        )
        key = (site.source.path, site.kind, target)
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        identities[index] = _site_id(
            site.source.path.as_posix(), site.kind, target, occurrence
        )
    return tuple(
        ArtifactSite(
            id=identities[index],
            kind=site.kind,
            source=site.source,
            targets=None if site.targets == "*" else site.targets,
            accept=site.accept,
        )
        for index, site in enumerate(sites)
    )


def media_accept(sites: Iterable[ArtifactSite]) -> dict[str, tuple[str, ...]]:
    """Return the media types a view reads each literal output target in.

    Inspection gives every literal read of a target the same list, and a host
    that selects its target at runtime declares none. An empty list reads
    marimo's native output.
    """
    accept: dict[str, tuple[str, ...]] = {}
    for site in sites:
        if site.kind == "output":
            for target in site.targets or ():
                accept.setdefault(target, site.accept)
    return accept


def inspection_sites(inspection: ProjectInspection) -> tuple[ArtifactSite, ...]:
    """Return the sites a view built from this inspection publishes."""
    return artifact_sites(inspection.sites)
