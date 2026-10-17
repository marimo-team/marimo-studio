"""Admit the regions a render locates in the files it published.

A region ties a rectangle on one surface of a rendered file to the notebook
results it shows. Studio keeps each region whose file, surface, and rectangle
it can check and that names a result the render reads, keeps only those
reads, and reports the rest as one warning, so a render with stray regions
still publishes its files. A region without a source takes the source of the
first read it shows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from marimo_export.values import SelectorStep, ValueSelector

from marimo_studio.view_providers._artifact_sites import ArtifactSite
from marimo_studio.view_providers._records import (
    ProjectDiagnostic,
    ProjectionKind,
    Rect,
    RenderRegion,
    SourceLocation,
)

MAX_RENDER_REGIONS = 4_096
# A Lens selection carries at most 64 notebook sources.
MAX_REGION_READS = 64
MAX_REGION_READ = 4_096
MAX_REGION_LABEL = 256
MAX_REGION_PAGE = 100_000
# Typeset positions round at surface edges.
_EDGE = 1e-3
_DIGITS = 6


@dataclass(frozen=True)
class _Read:
    kind: ProjectionKind
    target: str
    root: str | None
    path: tuple[SelectorStep, ...]
    source: SourceLocation


def _reads(sites: tuple[ArtifactSite, ...]) -> list[_Read]:
    reads: list[_Read] = []
    for site in sites:
        for target in site.targets or ():
            selector = None
            if site.kind != "cell":
                with suppress(ValueError):
                    selector = ValueSelector(target)
            reads.append(
                _Read(
                    site.kind,
                    target,
                    selector.root if selector else None,
                    tuple(selector.path) if selector else (),
                    site.source,
                )
            )
    return reads


def _read(read: str, reads: list[_Read]) -> _Read | None:
    """Return the render read that ``read`` names, or narrows with selector steps."""
    for item in reads:
        if item.target == read:
            return item
    try:
        selector = ValueSelector(read)
    except ValueError:
        return None
    path = tuple(selector.path)
    for item in reads:
        if (
            item.root == selector.root
            and len(path) > len(item.path)
            and path[: len(item.path)] == item.path
        ):
            return item
    return None


def region_surface(media_type: str) -> str | None:
    """Return the kind of surface a region locates in a file of ``media_type``."""
    if media_type == "application/pdf":
        return "page"
    major = media_type.split("/", 1)[0]
    return major if major in ("image", "video") else None


def _rect(rect: Rect) -> Rect | str:
    values = (rect.x, rect.y, rect.width, rect.height)
    if not all(math.isfinite(value) for value in values):
        return "its rectangle must have finite coordinates"
    if (
        rect.width <= 0
        or rect.height <= 0
        or rect.x < -_EDGE
        or rect.y < -_EDGE
        or rect.x + rect.width > 1 + _EDGE
        or rect.y + rect.height > 1 + _EDGE
    ):
        return "its rectangle must lie inside the surface, in fractions from 0 to 1"
    x = round(min(max(rect.x, 0.0), 1.0), _DIGITS)
    y = round(min(max(rect.y, 0.0), 1.0), _DIGITS)
    width = round(min(rect.width, 1 - x), _DIGITS)
    height = round(min(rect.height, 1 - y), _DIGITS)
    if width <= 0 or height <= 0:
        return "its rectangle must cover part of the surface"
    return Rect(x, y, width, height)


def _admit(
    region: RenderRegion,
    files: Mapping[PurePosixPath, str],
    reads: list[_Read],
) -> tuple[RenderRegion | str, int]:
    """Return the admitted region, or why Studio leaves it out, and the number
    of reads it drops because the render does not read them."""
    media_type = files.get(region.file)
    if media_type is None:
        return f"it names {region.file.as_posix()}, which the render did not publish", 0
    surface = region_surface(media_type)
    if surface is None:
        return (
            f"{region.file.as_posix()} is {media_type}, not a PDF, image, or video",
            0,
        )
    if surface == "page":
        if region.page is None or not 1 <= region.page <= MAX_REGION_PAGE:
            return "a region of a PDF names its page, counted from 1", 0
    elif region.page is not None:
        return f"a region of {media_type} has no page", 0
    if surface != "video" and (region.start is not None or region.end is not None):
        return f"a region of {media_type} has no start or end time", 0
    start = None if region.start is None else round(region.start, _DIGITS)
    end = None if region.end is None else round(region.end, _DIGITS)
    if start is not None and not (math.isfinite(start) and start >= 0):
        return "its start time must be a finite number of seconds from 0", 0
    if end is not None and not (math.isfinite(end) and end > (start or 0)):
        return "its end time must come after its start time", 0
    rect = _rect(region.rect)
    if isinstance(rect, str):
        return rect, 0
    known = [(read, _read(read, reads)) for read in dict.fromkeys(region.reads)]
    shown = [(read, item) for read, item in known if item is not None]
    if not shown:
        return "it names no result the render reads", 0
    source = region.source or next((item.source for _, item in shown), None)
    return (
        replace(
            region,
            rect=rect,
            reads=tuple(read for read, _ in shown),
            source=source,
            start=start,
            end=end,
        ),
        len(known) - len(shown),
    )


def admit_regions(
    regions: tuple[RenderRegion, ...],
    files: Mapping[PurePosixPath, str],
    sites: tuple[ArtifactSite, ...],
) -> tuple[tuple[RenderRegion, ...], tuple[ProjectDiagnostic, ...]]:
    """Return the regions Studio can show and a warning about the rest.

    ``files`` maps each published file to its media type, and ``sites`` are
    the render's read sites. A region keeps the reads that name or narrow a
    target the render reads.
    """
    reads = _reads(sites)
    admitted: list[RenderRegion] = []
    rejected: list[str] = []
    unknown = 0
    for region in regions:
        checked, dropped = _admit(region, files, reads)
        unknown += dropped
        if isinstance(checked, str):
            rejected.append(checked)
        else:
            admitted.append(checked)
    problems: list[str] = []
    if rejected:
        count = "1 region" if len(rejected) == 1 else f"{len(rejected)} regions"
        problems.append(
            f"Studio left out {count} of the render. The first: {rejected[0]}."
        )
    if unknown:
        count = "1 read" if unknown == 1 else f"{unknown} reads"
        problems.append(f"Studio left out {count} that the render does not read.")
    if not problems:
        return tuple(admitted), ()
    return tuple(admitted), (
        ProjectDiagnostic(
            "render-regions-invalid",
            "warning",
            " ".join(problems),
            "Locate each region on a published PDF page, image, or video "
            "frame, and name only results the render reads.",
        ),
    )
