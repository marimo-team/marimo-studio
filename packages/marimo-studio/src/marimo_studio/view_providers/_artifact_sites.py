"""Derive artifact sites from provider projection sites and render reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from marimo_studio.view_providers._records import (
    ProjectInspection,
    ProjectionKind,
    ProjectionSite,
    Render,
    Size,
    SourceLocation,
)

SITE_ATTRIBUTE = "data-marimo-studio-site"
# A render reads each value as JSON, with tables as rows and dates as text.
JSON_ACCEPT = ("application/json",)


@dataclass(frozen=True)
class ArtifactSite:
    """One artifact-local projection site with its Studio-assigned identity.

    A page host's site has no ``render``. A render read's site names the source
    of its render, such as ``main.typ``, and reads its one target on its own
    terms: an output in the first of ``accept`` the value supports, drawn at
    ``size`` when the build measured one, and a value as ``JSON_ACCEPT``, with
    tables as rows. A page output site with ``accept`` reads an image, and
    without it marimo's native output.
    """

    id: str
    kind: ProjectionKind
    source: SourceLocation
    targets: tuple[str, ...] | None
    accept: tuple[str, ...] = ()
    size: Size | None = None
    render: PurePosixPath | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source.to_dict(),
            "targets": (list(self.targets) if self.targets is not None else None),
            "accept": list(self.accept),
            "size": (
                {"width": self.size.width, "height": self.size.height}
                if self.size is not None
                else None
            ),
            "render": self.render.as_posix() if self.render is not None else None,
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


def render_sites(
    renders: tuple[Render, ...],
    output_sizes: Mapping[PurePosixPath, Mapping[str, Size]] | None = None,
) -> tuple[ArtifactSite, ...]:
    """Return one site per target each render reads, at its first read.

    Values read as JSON, and each output reads at the size the build measured
    for its render. Read IDs use their own namespace per render, so they
    never match a projection site's or another render's.
    """
    sites: dict[tuple[PurePosixPath, ProjectionKind, str], ArtifactSite] = {}

    def add(
        render: PurePosixPath,
        kind: ProjectionKind,
        target: str,
        source: SourceLocation,
        accept: tuple[str, ...],
        size: Size | None = None,
    ) -> None:
        if (render, kind, target) not in sites:
            sites[render, kind, target] = ArtifactSite(
                id=_site_id("read", render.as_posix(), kind, target),
                kind=kind,
                source=source,
                targets=(target,),
                accept=accept,
                size=size,
                render=render,
            )

    for render in renders:
        name = render.source
        sizes = (output_sizes or {}).get(name, {})
        for value in render.values:
            add(name, "value", value.target, value.source, JSON_ACCEPT)
        for output in render.outputs:
            add(
                name,
                "output",
                output.target,
                output.source,
                output.accept,
                sizes.get(output.target),
            )
        for cell in render.cells:
            add(name, "cell", cell.target, cell.source, cell.accept)
    return tuple(sites.values())


def page_sites(sites: Iterable[ArtifactSite]) -> tuple[ArtifactSite, ...]:
    """Return the sites of the page's own hosts, without render reads."""
    return tuple(site for site in sites if site.render is None)


def read_sites(
    sites: Iterable[ArtifactSite], render: PurePosixPath
) -> tuple[ArtifactSite, ...]:
    """Return the sites the render of ``render`` reads, in declaration order."""
    return tuple(site for site in sites if site.render == render)


def media_accept(
    sites: Iterable[ArtifactSite],
    kind: ProjectionKind,
) -> dict[str, tuple[str, ...]]:
    """Return the media types a page reads each literal output or cell target in.

    Inspection gives every literal page host of a target the same list, and a
    host that selects its target at runtime declares none. An empty output list
    reads marimo's native output. Render reads keep their own lists.
    """
    accept: dict[str, tuple[str, ...]] = {}
    for site in page_sites(sites):
        if site.kind == kind:
            for target in site.targets or ():
                accept.setdefault(target, site.accept)
    return accept


def inspection_sites(inspection: ProjectInspection) -> tuple[ArtifactSite, ...]:
    """Return the sites a view built from this inspection publishes."""
    return (*artifact_sites(inspection.sites), *render_sites(inspection.renders))
