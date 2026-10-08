"""Publish provider documents behind a Studio viewer page.

A provider with ``render()`` publishes a private template. Studio renders it
once without notebook values to check it and to give the page a first
document, then renders it again whenever the reader's values change. A
provider without ``render()`` whose build returns a PDF, SVG, or PNG publishes
that file.

Either way, the published entry is a small HTML page with a
``<marimo-document>`` viewer. Each value the template reads gets a hidden
``mo-value`` host inside the viewer, and each output it reads gets a hidden
``marimo-output`` host whose site accepts the media types the template can
place. Every runtime authorizes those targets, renders outputs in an accepted
media type, and reports changes through the ordinary projection path.
"""

from __future__ import annotations

import hashlib
import html
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from marimo_export.wire import canonical_json_bytes, parse_canonical_json

from marimo_studio._artifacts.limits import ARTIFACT_OUTPUT_BUDGET
from marimo_studio._artifacts.publication import TemplateCandidate
from marimo_studio._filesystem.errors import FileTooLargeError
from marimo_studio._filesystem.files import FileTree
from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio._views.records import DiagnosticsError
from marimo_studio.errors import MarimoStudioError
from marimo_studio.view_providers import (
    BuildResult,
    JsonValue,
    ProjectDiagnostic,
    ProjectionKind,
    ProviderCancellation,
    RenderRequest,
    Representation,
)
from marimo_studio.view_providers._artifact_sites import (
    SITE_ATTRIBUTE,
    ArtifactSite,
    media_accept,
)
from marimo_studio.view_providers._records import DOCUMENT_MEDIA_TYPES

SHELL_DOCUMENT = PurePosixPath("index.html")
RENDER_COMMAND_TIMEOUT = 60.0
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
# What one document render reads: values as compact JSON, and outputs, such as
# several large figures, as bytes.
MAX_DOCUMENT_VALUE_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_OUTPUT_BYTES = 16 * 1024 * 1024


class DocumentRenderer(Protocol):
    renders: bool

    def render(self, request: RenderRequest) -> BuildResult: ...


@dataclass(frozen=True)
class Rendition:
    """One rendered document file."""

    content: bytes
    suffix: str
    warnings: tuple[ProjectDiagnostic, ...]

    @property
    def media_type(self) -> str:
        return DOCUMENT_MEDIA_TYPES[self.suffix]


@dataclass(frozen=True)
class ViewOutput:
    """The entry, sites, and private template one build publishes."""

    document: PurePosixPath
    sites: tuple[ArtifactSite, ...]
    template: TemplateCandidate | None
    diagnostics: tuple[ProjectDiagnostic, ...]


def renderer_missing() -> ProjectDiagnostic:
    return ProjectDiagnostic(
        "document-renderer-missing",
        "error",
        "The view reads notebook values, and its provider has no render().",
        "Choose a provider that renders documents with notebook values.",
    )


def value_not_json(target: str, problem: str | None = None) -> ProjectDiagnostic:
    """Report a render value that is a table or is not portable JSON."""
    return ProjectDiagnostic(
        "render-value-not-json",
        "error",
        f"Documents read JSON values: {problem}."
        if problem
        else f"{target} is a table, and documents read JSON values.",
        "Project tables as a list of dictionaries in the notebook, for example "
        "with df.to_dicts().",
    )


def canonical_values(
    values: Mapping[str, object],
) -> tuple[dict[str, JsonValue], bytes]:
    """Return render values as portable JSON data and its canonical bytes.

    Portable JSON spells numbers as JavaScript does, so a Python kernel, a
    browser runtime, and a prepared export that produce the same number render
    the same document and share one cached rendition.
    """
    normalized: dict[str, JsonValue] = {}
    for target, value in values.items():
        try:
            normalized[target] = parse_canonical_json(
                canonical_json_bytes(value, target), target
            )
        except (TypeError, ValueError) as error:
            raise DiagnosticsError((value_not_json(target, str(error)),)) from error
    return normalized, canonical_json_bytes(normalized)


def document_targets(
    sites: tuple[ArtifactSite, ...],
    kind: ProjectionKind,
) -> set[str]:
    """Return the notebook targets of one kind a document view's template reads."""
    return {
        target for site in sites if site.kind == kind for target in site.targets or ()
    }


class RenderInputError(ValueError):
    """A render names a target the document does not read, or unaccepted media."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def admit_render_inputs(
    sites: tuple[ArtifactSite, ...],
    values: Mapping[str, object],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
) -> None:
    """Raise ``RenderInputError`` unless the document reads every input as given."""
    unknown = sorted(set(values) - document_targets(sites, "value"))
    reads: tuple[tuple[ProjectionKind, Mapping[str, Representation]], ...] = (
        ("output", outputs),
        ("cell", cells),
    )
    for kind, media in reads:
        accept = media_accept(sites, kind)
        unknown.extend(sorted(set(media) - set(accept)))
        for target in sorted(set(media) & set(accept)):
            media_type = media[target].media_type
            if media_type not in accept[target]:
                raise RenderInputError(
                    f"render-{kind}-not-accepted",
                    f"The document reads {target!r} as {', '.join(accept[target])}, "
                    f"not {media_type}.",
                )
    if unknown:
        raise RenderInputError(
            "render-target-not-allowed", f"The document does not read {unknown[0]!r}."
        )


def render_key(
    encoded_values: bytes,
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
) -> bytes:
    """Return the digest that identifies one render's values, outputs, and cells."""
    digest = hashlib.sha256(encoded_values)
    for kind, media in (("output", outputs), ("cell", cells)):
        for target in sorted(media):
            item = media[target]
            fields = {**asdict(item), "data": hashlib.sha256(item.data).hexdigest()}
            digest.update(f"\0{kind}\0{target}\0".encode())
            digest.update(json.dumps(fields, sort_keys=True).encode())
    return digest.digest()


def _host(site: ArtifactSite, target: str) -> str:
    escaped = html.escape(target, quote=True)
    if site.kind == "output":
        return (
            f'\n<marimo-output hidden value="{escaped}" '
            f'{SITE_ATTRIBUTE}="{site.id}"></marimo-output>'
        )
    if site.kind == "cell":
        return (
            f'\n<marimo-cell hidden name="{escaped}" '
            f'{SITE_ATTRIBUTE}="{site.id}"></marimo-cell>'
        )
    return f'\n<span hidden mo-value="{escaped}" {SITE_ATTRIBUTE}="{site.id}"></span>'


def document_shell(
    title: str,
    source: PurePosixPath,
    sites: tuple[ArtifactSite, ...],
    *,
    renders: bool,
) -> str:
    """Return the viewer page for one published document."""
    media_type = DOCUMENT_MEDIA_TYPES[source.suffix.lower()]
    hosts = "".join(
        _host(site, target) for site in sites for target in site.targets or ()
    )
    render = " render" if renders else ""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        "<style>html,body{margin:0;min-height:100%}</style>\n"
        '</head>\n<body>\n<main id="app-shell">\n'
        f'<marimo-document src="{html.escape(source.as_posix(), quote=True)}" '
        f'type="{media_type}"{render}>{hosts}\n</marimo-document>\n'
        "</main>\n</body>\n</html>\n"
    )


def _over_budget(code: str, kind: str, limit: int) -> DiagnosticsError:
    return DiagnosticsError(
        (
            ProjectDiagnostic(
                code,
                "error",
                f"The {kind} this document reads exceed {limit // 2**20} MiB.",
                f"Read fewer or smaller {kind} in the document.",
            ),
        )
    )


def check_render_budget(
    values: Mapping[str, JsonValue],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
) -> None:
    """Raise ``DiagnosticsError`` when a render reads more than its budgets."""
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > MAX_DOCUMENT_VALUE_BYTES:
        raise _over_budget(
            "document-values-too-large", "values", MAX_DOCUMENT_VALUE_BYTES
        )
    media = (*outputs.values(), *cells.values())
    if sum(len(item.data) for item in media) > MAX_DOCUMENT_OUTPUT_BYTES:
        raise _over_budget(
            "document-outputs-too-large", "outputs", MAX_DOCUMENT_OUTPUT_BYTES
        )


def render_document(
    renderer: DocumentRenderer,
    copy_template: Callable[[Path], object],
    document: PurePosixPath,
    values: Mapping[str, JsonValue],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
    cancellation: ProviderCancellation,
) -> Rendition:
    """Render a private, writable copy of a template.

    ``copy_template`` writes the template into the directory it receives.
    Raises ``DiagnosticsError`` with the render diagnostics when no document
    renders. A provider failure after cancellation propagates unchanged.
    """
    check_render_budget(values, outputs, cells)
    with tempfile.TemporaryDirectory(prefix="marimo-studio-render-") as scratch:
        template_root = Path(scratch, "template")
        output_root = Path(scratch, "output")
        output_root.mkdir()
        try:
            copy_template(template_root)
            result = renderer.render(
                RenderRequest(
                    template_root=template_root,
                    document=document,
                    values=values,
                    outputs=outputs,
                    cells=cells,
                    output_root=output_root,
                    cancellation=cancellation,
                    runner=create_provider_runner(
                        template_root,
                        cancellation,
                        RENDER_COMMAND_TIMEOUT,
                    ),
                    command_timeout=RENDER_COMMAND_TIMEOUT,
                )
            )
        except MarimoStudioError as error:
            if cancellation.cancelled:
                raise
            raise DiagnosticsError(
                (
                    ProjectDiagnostic(
                        "document-render-failed",
                        "error",
                        str(error),
                        f"Fix {document}, or read fewer notebook results in it, "
                        "then save it to render again.",
                    ),
                )
            ) from error
        errors = tuple(item for item in result.diagnostics if item.severity == "error")
        if result.document is None or errors:
            raise DiagnosticsError(
                errors
                or (
                    ProjectDiagnostic(
                        "document-render-failed",
                        "error",
                        f"The provider rendered no document from {document}.",
                    ),
                )
            )
        rendered = output_root.joinpath(*result.document.parts)
        try:
            content = (
                FileTree(output_root)
                .read(rendered, max_bytes=MAX_DOCUMENT_BYTES)
                .content
            )
        except FileTooLargeError as error:
            raise DiagnosticsError(
                (
                    ProjectDiagnostic(
                        "document-render-too-large",
                        "error",
                        f"The rendered document exceeds "
                        f"{MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB.",
                    ),
                )
            ) from error
        return Rendition(
            content,
            rendered.suffix.lower(),
            tuple(item for item in result.diagnostics if item.severity == "warning"),
        )


def compose_view(
    *,
    generation_root: Path,
    files_root: Path,
    document: PurePosixPath,
    sites: tuple[ArtifactSite, ...],
    document_sites: tuple[ArtifactSite, ...],
    title: str,
    renderer: DocumentRenderer,
    renderer_fingerprint: str,
    cancellation: ProviderCancellation,
) -> ViewOutput:
    """Arrange the files one build publishes from its staging root.

    An HTML page publishes as built. For a document, Studio ingests the build
    output into a directory only Studio writes, and ``files_root`` then holds
    the viewer page and the document it shows.
    """
    if not renderer.renders and document.suffix.lower() == ".html":
        return ViewOutput(document, sites, None, ())
    if sites:
        raise DiagnosticsError(
            (
                ProjectDiagnostic(
                    "projection-site-unsupported",
                    "error",
                    f"{document} is a document, and projection hosts need an "
                    "HTML page.",
                    "Read notebook values through the document's render values, "
                    "or build an HTML page.",
                ),
            )
        )
    if not renderer.renders and document.suffix.lower() not in DOCUMENT_MEDIA_TYPES:
        raise DiagnosticsError(
            (
                ProjectDiagnostic(
                    "document-type-unsupported",
                    "error",
                    f"Studio cannot display {document.as_posix()}.",
                    "Build an HTML page, or a PDF, SVG, or PNG document.",
                ),
            )
        )
    built = generation_root / ("template" if renderer.renders else "document")
    tree = FileTree(generation_root)
    tree.ingest(
        files_root,
        built,
        budget=ARTIFACT_OUTPUT_BUDGET,
        label="Document output",
    )
    tree.remove(files_root)
    tree.create_directory(files_root)
    template = None
    if renderer.renders:
        rendition = render_document(
            renderer,
            lambda destination: shutil.copytree(built, destination),
            document,
            {},
            {},
            {},
            cancellation,
        )
        sites = document_sites
        template = TemplateCandidate(built, document, renderer_fingerprint)
    else:
        rendition = Rendition(
            tree.read(
                built.joinpath(*document.parts), max_bytes=MAX_DOCUMENT_BYTES
            ).content,
            document.suffix.lower(),
            (),
        )
    published = PurePosixPath(document.stem + rendition.suffix)
    files_root.joinpath(published).write_bytes(rendition.content)
    files_root.joinpath(SHELL_DOCUMENT).write_text(
        document_shell(title, published, sites, renders=renderer.renders),
        encoding="utf-8",
    )
    return ViewOutput(SHELL_DOCUMENT, sites, template, rendition.warnings)
