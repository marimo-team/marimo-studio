"""Turn projection host start tags into projection sites."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

from marimo_studio._filesystem.paths import validate_relative_path
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers._artifact_sites import SITE_ATTRIBUTE
from marimo_studio.view_providers._document import HTMLDocumentParser
from marimo_studio.view_providers._records import (
    ProjectDiagnostic,
    ProjectionKind,
    ProjectionSite,
    SourceLocation,
)
from marimo_studio.view_providers._targets import validate_projection_target
from marimo_studio.view_providers._validation import parse_accept

_USAGE_HINT = (
    'Use <marimo-cell name="..."> for a complete cell display, '
    '<marimo-output value="..."> for one Python object, '
    '<marimo-output render="..."> for a file the view provider renders, '
    'or mo-value="..." when browser code needs JSON-compatible data.'
)
# The attribute that holds each kind's target, the host it belongs to, and the
# name of the target in messages.
_TARGETS: dict[ProjectionKind, tuple[str, str, str]] = {
    "cell": ("name", "<marimo-cell>", "name"),
    "output": ("value", "<marimo-output>", "value"),
    "value": ("mo-value", "mo-value", "selector"),
}
_RENDER_CONFLICTS = ("value", "accept", "data-marimo-allow")


def _text(attributes: Mapping[str, str | None], name: str) -> str | None:
    """Return an attribute's text, ``""`` when it has no value, or ``None``."""
    return (attributes[name] or "") if name in attributes else None


def host_site(
    tag: str,
    attributes: Mapping[str, str | None],
    source: SourceLocation,
    offset: int,
    *,
    nested: bool = False,
) -> ProjectionSite | ProjectDiagnostic | None:
    """Return the projection site one host start tag declares.

    ``attributes`` maps each attribute name to its value, or to ``None`` for an
    attribute written without one. ``source`` locates the start tag, and
    ``offset`` is the UTF-8 byte offset where Studio inserts the site attribute.
    ``nested`` marks a start tag inside a ``marimo-cell``, ``marimo-output``,
    or ``mo-value`` element. Returns ``None`` for an element that declares no
    site, including a valid ``<marimo-output render>`` host, and a diagnostic
    located at ``source`` for a host Studio cannot project.
    """

    if SITE_ATTRIBUTE in attributes:
        return ProjectDiagnostic(
            "projection-site-reserved",
            "error",
            f"{SITE_ATTRIBUTE} is reserved for Studio.",
            f"Remove {SITE_ATTRIBUTE}. Studio adds it to built hosts.",
            source,
        )
    return built_host_site(tag, attributes, source, offset, nested=nested)


def built_host_site(
    tag: str,
    attributes: Mapping[str, str | None],
    source: SourceLocation,
    offset: int,
    *,
    nested: bool,
) -> ProjectionSite | ProjectDiagnostic | None:
    """Apply ``host_site()``'s rules to a host that may carry its site attribute.

    Built pages keep the site attribute Studio inserted, so publication checks
    their hosts with every rule except the reserved attribute.
    """

    def problem(code: str, message: str, hint: str = _USAGE_HINT) -> ProjectDiagnostic:
        return ProjectDiagnostic(code, "error", message, hint, source)

    kinds: list[ProjectionKind] = []
    if tag == "marimo-cell":
        kinds.append("cell")
    elif tag == "marimo-output":
        kinds.append("output")
    if "mo-value" in attributes:
        kinds.append("value")
    if not kinds:
        return None
    if len(kinds) > 1:
        return problem(
            "projection-kind-conflict",
            "One element cannot declare more than one projection kind.",
        )
    if nested:
        return problem(
            "projection-host-nested",
            "Projection hosts cannot contain other projection hosts.",
            "Place the hosts beside each other.",
        )
    kind = kinds[0]
    if kind == "output" and "render" in attributes:
        conflict = next(
            (name for name in _RENDER_CONFLICTS if name in attributes), None
        )
        if conflict is not None:
            return problem(
                "projection-render-invalid",
                f"<marimo-output render> cannot also set {conflict}.",
                'Show a render with <marimo-output render="main.typ">, '
                'or a notebook value with <marimo-output value="chart">.',
            )
        try:
            validate_relative_path(
                (attributes["render"] or "").strip(), field="<marimo-output> render"
            )
        except ValueError as error:
            return problem(
                "projection-render-invalid",
                str(error),
                "Name the project file the render starts from, such as main.typ.",
            )
        return None
    attribute, subject, noun = _TARGETS[kind]
    target = (attributes.get(attribute) or "").strip()
    if not target:
        return problem(
            "projection-target-missing", f"{subject} requires a non-empty {noun}."
        )
    try:
        target = validate_projection_target(kind, target)
    except ValueError as error:
        return problem(
            "projection-target-invalid", f"Invalid {subject} {noun}: {error}"
        )
    allow = _text(attributes, "data-marimo-allow")
    if allow not in (None, "*"):
        return problem(
            "projection-wildcard-invalid",
            'data-marimo-allow must be the literal "*".',
            'Add data-marimo-allow="*" to a projection host whose selector page '
            "JavaScript changes at runtime.",
        )
    try:
        accept = parse_accept(kind, _text(attributes, "accept"))
    except ValueError as error:
        return problem(
            "projection-accept-invalid",
            f"The accept attribute is invalid: {error}.",
            'List image types, such as accept="image/svg+xml image/png".',
        )
    return ProjectionSite(
        kind, "*" if allow == "*" else (target,), source, offset, accept
    )


def html_sites(
    path: PurePosixPath,
    source: bytes,
) -> tuple[tuple[ProjectionSite, ...], tuple[ProjectDiagnostic, ...]]:
    """Find the ``marimo-cell``, ``marimo-output``, and ``mo-value`` hosts.

    ``source`` holds the file bytes as stored, so each site's ``offset`` points
    into the same bytes Studio instruments. Each host goes through
    ``host_site()``. Markup that is not valid HTML reports one diagnostic, and
    the hosts before it keep their results.
    """
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return (), (
            ProjectDiagnostic(
                code="source-document-invalid",
                severity="error",
                message=f"{path} must be UTF-8 text.",
                source=SourceLocation(path, 1, 1),
            ),
        )
    parser = HTMLDocumentParser(resources=False)
    failure: ProjectDiagnostic | None = None
    try:
        parser.feed(text)
        parser.close()
    except ViewProjectError as error:
        failure = ProjectDiagnostic(
            code="source-document-invalid",
            severity="error",
            message=str(error),
            hint=vars(error).get("public_hint", _USAGE_HINT),
            source=SourceLocation(path, error.line or 1, error.column or 1),
        )
    sites: list[ProjectionSite] = []
    diagnostics: list[ProjectDiagnostic] = []
    for host in parser.hosts:
        result = host_site(
            host.tag,
            host.attributes,
            SourceLocation(path, *host.position),
            host.insertion_offset,
            nested=host.nested,
        )
        if isinstance(result, ProjectionSite):
            sites.append(result)
        elif result is not None:
            diagnostics.append(result)
    if failure is not None:
        diagnostics.append(failure)
    return tuple(sites), tuple(diagnostics)
