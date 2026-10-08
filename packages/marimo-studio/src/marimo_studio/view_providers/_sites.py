"""Find projection hosts in HTML source."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers._artifact_sites import SITE_ATTRIBUTE
from marimo_studio.view_providers._document import (
    PROJECTION_USAGE_HINT,
    HTMLDocumentParser,
)
from marimo_studio.view_providers._records import (
    ProjectDiagnostic,
    ProjectionSite,
    SourceLocation,
)
from marimo_studio.view_providers._validation import parse_accept


def html_sites(
    path: PurePosixPath,
    source: bytes,
) -> tuple[tuple[ProjectionSite, ...], tuple[ProjectDiagnostic, ...]]:
    """Find ``marimo-cell``, ``marimo-output``, and ``mo-value`` hosts.

    ``source`` holds the file bytes as stored, so each site's ``offset`` points
    into the same bytes Studio instruments. Hosts found before an invalid one
    are returned with its diagnostic.
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
    diagnostics: list[ProjectDiagnostic] = []
    try:
        parser.feed(text)
        parser.close()
    except ViewProjectError as error:
        diagnostics.append(
            ProjectDiagnostic(
                code="source-document-invalid",
                severity="error",
                message=str(error),
                hint=vars(error).get("public_hint", PROJECTION_USAGE_HINT),
                source=SourceLocation(path, error.line or 1, error.column or 1),
            )
        )
    if parser.authored_site_attribute_position is not None:
        line, column = parser.authored_site_attribute_position
        diagnostics.append(
            ProjectDiagnostic(
                code="projection-site-reserved",
                severity="error",
                message=f"{SITE_ATTRIBUTE} is reserved for Studio.",
                hint=f"Remove {SITE_ATTRIBUTE}. Studio adds it to built hosts.",
                source=SourceLocation(path, line, column),
            )
        )
    sites: list[ProjectionSite] = []
    for host in parser.hosts:
        line, column = host.position
        if host.allow not in (None, "*"):
            diagnostics.append(
                ProjectDiagnostic(
                    code="projection-wildcard-invalid",
                    severity="error",
                    message='data-marimo-allow must be the literal "*".',
                    hint=(
                        'Add data-marimo-allow="*" to a projection host whose '
                        "selector page JavaScript changes at runtime."
                    ),
                    source=SourceLocation(path, line, column),
                )
            )
            continue
        try:
            accept = parse_accept(host.kind, host.accept)
        except ValueError as error:
            diagnostics.append(
                ProjectDiagnostic(
                    code="projection-accept-invalid",
                    severity="error",
                    message=f"The accept attribute is invalid: {error}.",
                    hint='List image types, such as accept="image/svg+xml image/png".',
                    source=SourceLocation(path, line, column),
                )
            )
            continue
        sites.append(
            ProjectionSite(
                kind=host.kind,
                targets="*" if host.allow == "*" else (host.target,),
                source=SourceLocation(path, line, column),
                offset=host.insertion_offset,
                accept=accept,
            )
        )
    return tuple(sites), tuple(diagnostics)
