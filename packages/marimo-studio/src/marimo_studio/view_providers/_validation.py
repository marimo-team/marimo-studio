"""Pure validation for provider-owned records."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from pathlib import PurePosixPath

from marimo_export.values import normalize_accept

from marimo_studio._filesystem.paths import (
    validate_relative_path,
)
from marimo_studio.view_providers._artifact_sites import ArtifactSite
from marimo_studio.view_providers._records import (
    ProjectDiagnostic,
    ProjectionKind,
    ProjectionSite,
    RenderCell,
    RenderOutput,
    RenderValue,
    SourceLocation,
)
from marimo_studio.view_providers._targets import (
    MAX_CELL_TARGETS,
    MAX_VALUE_TARGETS,
    validate_projection_target,
)

MAX_PROVIDER_TEXT_BYTES = 64 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1

_PROJECTION_SITE_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")
_PROVIDER_KEY = re.compile(
    r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?"
)


def validate_projection_site_id(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _PROJECTION_SITE_ID.fullmatch(value) is None
        or value != value.strip()
    ):
        raise ValueError(f"{field} must be a lowercase artifact-local identifier")
    return value


def validate_provider_key(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _PROVIDER_KEY.fullmatch(value) is None
        or value != value.strip()
    ):
        raise ValueError(f"{field} must use distribution/entry-point form")
    return value


def _validate_source_location(
    source: object,
    documents: Collection[PurePosixPath] | None,
    *,
    label: str,
) -> SourceLocation:
    if not isinstance(source, SourceLocation):
        raise ValueError(f"{label} must be a SourceLocation")
    if type(source.path) is not PurePosixPath:
        raise ValueError(f"{label} path must be a PurePosixPath")
    path = validate_relative_path(source.path, field=f"{label} path")
    if len(path.as_posix().encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES:
        raise ValueError(
            f"{label} path exceeds the {MAX_PROVIDER_TEXT_BYTES}-byte limit"
        )
    if documents is not None:
        catalog = {
            validate_relative_path(item, field=f"{label} document path")
            for item in documents
        }
        if path not in catalog:
            raise ValueError(
                f"{label} path {path.as_posix()!r} is absent from documents"
            )
    if (
        type(source.line) is not int
        or type(source.column) is not int
        or source.line <= 0
        or source.column <= 0
        or source.line > MAX_SAFE_INTEGER
        or source.column > MAX_SAFE_INTEGER
    ):
        raise ValueError(f"{label} coordinates must be positive browser-safe integers")
    return source


def _validate_targets(kind: str, value: object) -> None:
    if value == "*":
        return
    if not isinstance(value, tuple) or not value:
        raise ValueError('Projection site targets must be a non-empty tuple or "*"')
    maximum = MAX_CELL_TARGETS if kind == "cell" else MAX_VALUE_TARGETS
    if len(value) > maximum:
        raise ValueError(f"Projection site targets exceed the {maximum}-target limit")
    targets = tuple(validate_projection_target(kind, target) for target in value)
    if len(set(targets)) != len(targets):
        raise ValueError("Projection site targets must be unique")


def validate_projection_site(
    value: object,
    *,
    documents: Collection[PurePosixPath] | None = None,
) -> ProjectionSite:
    if not isinstance(value, ProjectionSite):
        raise ValueError("Projection site must be a ProjectionSite record")
    if value.kind not in {"cell", "output", "value"}:
        raise ValueError("Projection site kind is invalid")
    _validate_source_location(value.source, documents, label="Projection source")
    _validate_targets(value.kind, value.targets)
    _validate_accept(value.kind, value.accept, optional=True)
    _validate_page_media(value.accept)
    if (
        type(value.offset) is not int
        or value.offset < 0
        or value.offset > MAX_SAFE_INTEGER
    ):
        raise ValueError("Projection site offset must be a non-negative byte offset")
    return value


class InvalidTargetError(ValueError):
    """A record names a notebook target that does not parse."""

    def __init__(self, message: str, source: SourceLocation) -> None:
        super().__init__(message)
        self.source = source


# Images marimo's output renderer shows in a page's <marimo-output> host.
PAGE_MEDIA_TYPES = ("image/svg+xml", "image/png", "image/jpeg", "image/gif")


def parse_accept(kind: ProjectionKind, text: str | None) -> tuple[str, ...]:
    """Parse the ``accept`` attribute of a projection host of ``kind``.

    An output host lists images a page shows, in preference order, separated by
    commas or whitespace. ``None``, for a host without the attribute, returns an
    empty tuple. Raises ``ValueError`` describing the first problem, including
    an ``accept`` on a cell or value host.
    """
    if text is None:
        return ()
    if kind != "output":
        raise ValueError("only <marimo-output> hosts accept media types")
    items = [item.lower() for item in re.split(r"[\s,]+", text) if item]
    _validate_page_media(items)
    return normalize_accept(items)


def _validate_page_media(accept: Iterable[str]) -> None:
    for media_type in accept:
        if media_type not in PAGE_MEDIA_TYPES:
            raise ValueError(
                f"a page shows {', '.join(PAGE_MEDIA_TYPES)}, not {media_type}"
            )


def _validate_accept(
    kind: str,
    accept: object,
    *,
    optional: bool,
    kinds: Collection[str] = ("output",),
) -> None:
    if not isinstance(accept, tuple):
        raise ValueError("accept must be a tuple of media types")
    if not accept and optional:
        return
    if kind not in kinds:
        raise ValueError(f"Only {' and '.join(kinds)} sites accept media types")
    try:
        normalized = normalize_accept(accept)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Output accept list is invalid: {error}") from error
    if normalized != accept:
        raise ValueError("Output accept lists use lowercase type/subtype media types")


def render_read_kind(value: RenderValue | RenderOutput | RenderCell) -> ProjectionKind:
    if isinstance(value, RenderCell):
        return "cell"
    return "output" if isinstance(value, RenderOutput) else "value"


def validate_render_value(
    value: object,
    *,
    documents: Collection[PurePosixPath] | None = None,
) -> RenderValue | RenderOutput | RenderCell:
    """Validate a document's value, output, or cell read and its target."""
    if not isinstance(value, (RenderValue, RenderOutput, RenderCell)):
        raise ValueError(
            "Render reads must be RenderValue, RenderOutput, or RenderCell records"
        )
    kind = render_read_kind(value)
    source = _validate_source_location(
        value.source, documents, label=f"Render {kind} source"
    )
    if not isinstance(value, RenderValue):
        _validate_accept(kind, value.accept, optional=False, kinds=("output", "cell"))
    try:
        validate_projection_target(kind, value.target)
    except ValueError as error:
        raise InvalidTargetError(str(error), source) from error
    return value


def accept_diagnostics(
    sites: Collection[ProjectionSite],
    reads: Iterable[RenderOutput | RenderCell],
) -> tuple[ProjectDiagnostic, ...]:
    """Report output and cell reads whose media types the view cannot resolve.

    A view reads each output or cell target once, so every host and document
    read of one target accepts the same media types. A host that selects its
    target at runtime reads it in the media types its literal reads declare.
    """
    conflicts = [
        ProjectDiagnostic(
            "projection-accept-invalid",
            "error",
            "An output host that selects its target at runtime cannot declare accept.",
            "List the host's targets, or remove accept to show marimo's output.",
            site.source,
        )
        for site in sites
        if site.kind == "output" and site.targets == "*" and site.accept
    ]
    first: dict[tuple[str, str], tuple[tuple[str, ...], SourceLocation]] = {}

    def check(
        kind: str,
        targets: Iterable[str],
        accept: tuple[str, ...],
        source: SourceLocation,
    ) -> None:
        # One conflict per host or read keeps the diagnostics within the
        # site and read counts.
        for target in targets:
            expected, location = first.setdefault((kind, target), (accept, source))
            if accept != expected:
                conflicts.append(
                    ProjectDiagnostic(
                        "output-accept-conflict",
                        "error",
                        f"{target} is read as {_media(accept)} here and as "
                        f"{_media(expected)} at {location.path}:{location.line}.",
                        f"Give every read of one {kind} the same accept list.",
                        source,
                    )
                )
                return

    for site in sites:
        if site.kind == "output" and site.targets != "*":
            check("output", site.targets, site.accept, site.source)
    for read in reads:
        check(render_read_kind(read), (read.target,), read.accept, read.source)
    return tuple(conflicts)


def _media(accept: tuple[str, ...]) -> str:
    return ", ".join(accept) if accept else "marimo's output"


def validate_artifact_site(value: object) -> ArtifactSite:
    if not isinstance(value, ArtifactSite):
        raise ValueError("Projection site must be an ArtifactSite record")
    validate_projection_site_id(value.id, field="Projection site ID")
    if value.kind not in {"cell", "output", "value"}:
        raise ValueError("Projection site kind is invalid")
    _validate_source_location(value.source, None, label="Projection source")
    _validate_targets(
        value.kind,
        "*" if value.targets is None else value.targets,
    )
    _validate_accept(value.kind, value.accept, optional=True, kinds=("output", "cell"))
    return value


def validate_project_diagnostic(
    value: object,
    *,
    documents: Collection[PurePosixPath] | None = None,
) -> ProjectDiagnostic:
    if not isinstance(value, ProjectDiagnostic):
        raise ValueError("Project diagnostic must be a ProjectDiagnostic record")
    if (
        not isinstance(value.code, str)
        or re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            value.code,
        )
        is None
    ):
        raise ValueError("Project diagnostic code must be canonical kebab-case")
    if value.severity not in {"warning", "error"}:
        raise ValueError("Project diagnostic severity must be warning or error")
    if not value.message or value.message != value.message.strip():
        raise ValueError("Project diagnostic message must be canonical")
    if value.hint != value.hint.strip():
        raise ValueError("Project diagnostic hint must be canonical")
    if len(value.message.encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES:
        raise ValueError("Project diagnostic message exceeds the text limit")
    if len(value.hint.encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES:
        raise ValueError("Project diagnostic hint exceeds the text limit")
    if value.source is not None:
        _validate_source_location(value.source, documents, label="Diagnostic source")
    return value
