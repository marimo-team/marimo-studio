"""Provide single-document HTML views with live notebook mounts.

The Vanilla provider gives a view author one editable HTML file containing the
page structure, styles, and scripts. It finds literal cell, output, and value
hosts, records their source locations, and adds stable mount IDs to the browser
file that Studio validates and publishes.

Projection hosts must live inside the page's application shell. Project-local
assets must be inlined into the HTML file, while external URLs, data URLs, and
page fragments remain available. This keeps the project small and directly
editable without a frontend build tool.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import PurePosixPath

from marimo_studio._filesystem.io import reject_mutable_symlinks
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    MountDeclaration,
    ProjectDiagnostic,
    ProjectInput,
    ProjectInspection,
    ProjectionKind,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    SourceLocation,
    StarterContext,
    StarterPlan,
    ViewProject,
    mount_attribute,
)
from marimo_studio.view_providers._bundled._starters import (
    create_starter,
    provider_starters,
)
from marimo_studio.view_providers._bundled.vanilla.starters import (
    catalog as _STARTERS,
)
from marimo_studio.view_providers._document import (
    HTMLDocumentParser,
    HTMLLocalResourceError,
    validate_html_document,
    validate_self_contained_html,
)
from marimo_studio.view_providers._validation import validate_relative_path

PROVIDER_KEY = "marimo-studio/vanilla"
_AGENT_INSTRUCTIONS_PATH = PurePosixPath("AGENTS.md")
_OPTIONAL_DESIGN_PATH = PurePosixPath("DESIGN.md")


def _site_id(path: PurePosixPath, kind: str, target: str, occurrence: int) -> str:
    identity = json.dumps(
        [PROVIDER_KEY, path.as_posix(), kind, target, occurrence],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"site-{hashlib.sha256(identity.encode()).hexdigest()}"


def _literal_site(
    path: PurePosixPath,
    kind: ProjectionKind,
    target: str,
    position: tuple[int, int],
    occurrence: int,
) -> MountDeclaration:
    line, column = position
    return MountDeclaration(
        id=_site_id(path, kind, target, occurrence),
        kind=kind,
        source=SourceLocation(path, line, column),
        allowed_targets=(target,),
    )


def _mounts(
    path: PurePosixPath,
    content: str,
) -> tuple[tuple[MountDeclaration, ...], tuple[int, ...]]:
    parser = HTMLDocumentParser()
    parser.feed(content)
    validate_html_document(parser, path.as_posix())
    validate_self_contained_html(parser, path.as_posix())
    if parser.projection_outside_shell:
        raise ValueError(f"{path}: projection hosts must be inside #app-shell")
    if parser.has_reserved_runtime_markup:
        raise ValueError(f"{path}: source contains reserved runtime markup")
    if parser.authored_mount_declaration_position is not None:
        line, column = parser.authored_mount_declaration_position
        raise ViewProjectError(
            "data-marimo-studio-site is reserved for Studio",
            source=path.as_posix(),
            line=line,
            column=column,
        )
    sites: list[MountDeclaration] = []
    offsets: list[int] = []
    occurrences: dict[tuple[ProjectionKind, str], int] = {}
    for kind in ("cell", "output", "value"):
        for declaration in parser.mounts:
            if declaration.kind != kind:
                continue
            key = (declaration.kind, declaration.target)
            occurrence = occurrences.get(key, 0)
            sites.append(
                _literal_site(
                    path,
                    declaration.kind,
                    declaration.target,
                    declaration.position,
                    occurrence,
                )
            )
            offsets.append(declaration.insertion_offset)
            occurrences[key] = occurrence + 1
    return tuple(sites), tuple(offsets)


def _instrument(
    path: PurePosixPath,
    content: str,
    expected: tuple[MountDeclaration, ...],
) -> str:
    current, offsets = _mounts(path, content)
    if current != expected:
        raise ValueError("Vanilla projection sites changed before the build started")
    source = content.encode("utf-8")
    parts: list[bytes] = []
    cursor = 0
    for site, offset in sorted(
        zip(current, offsets, strict=True),
        key=lambda item: item[1],
    ):
        if offset < cursor or offset > len(source):
            raise ValueError(f"Invalid Vanilla instrumentation offset in {path}")
        name, value = mount_attribute(site.id)
        parts.extend((source[cursor:offset], f' {name}="{value}"'.encode()))
        cursor = offset
    parts.append(source[cursor:])
    return b"".join(parts).decode("utf-8")


def _entry_path(project: ViewProject) -> PurePosixPath:
    unknown = sorted(set(project.options) - {"entrypoint"})
    if unknown:
        raise ValueError(f"Vanilla received undeclared option {unknown[0]!r}")
    configured = project.options.get("entrypoint", "index.html")
    if not isinstance(configured, (str, PurePosixPath)):
        raise ValueError("Vanilla entrypoint must be a project-relative POSIX path")
    entry = validate_relative_path(configured, field="Vanilla entrypoint")
    if entry.suffix.lower() != ".html":
        raise ValueError("Vanilla entrypoint must be an HTML document")
    return entry


def _entry_document(
    project: ViewProject,
    entry: PurePosixPath,
) -> SourceDocument:
    absolute_entry = project.root.joinpath(*entry.parts)
    reject_mutable_symlinks(
        project.root,
        {absolute_entry},
    )
    if not absolute_entry.is_file():
        raise ConfigurationError(f"Vanilla entry document is unavailable: {entry}")
    return SourceDocument(entry, "html", "edit")


def _guidance_documents(project: ViewProject) -> tuple[SourceDocument, ...]:
    documents: list[SourceDocument] = []
    for relative in (_AGENT_INSTRUCTIONS_PATH, _OPTIONAL_DESIGN_PATH):
        path = project.root / relative
        if not path.exists():
            continue
        reject_mutable_symlinks(project.root, {path})
        if not path.is_file():
            raise ConfigurationError(f"Vanilla guidance is unavailable: {relative}")
        documents.append(SourceDocument(relative, "markdown", "edit"))
    return tuple(documents)


class VanillaProvider:
    """Inspect and build browser-native view projects."""

    info = ProviderInfo(
        title="Vanilla web",
        summary="Builds one HTML document with inline styles and scripts.",
        api_version=1,
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        del project
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return provider_starters(_STARTERS)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        return create_starter(_STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        try:
            entry_path = _entry_path(project)
        except ValueError as error:
            return ProjectInspection(
                editor_documents=(),
                input_scope=(ProjectInput(PurePosixPath("view.toml"), "file"),),
                mounts=(),
                diagnostics=(
                    ProjectDiagnostic(
                        code="provider-options-invalid",
                        severity="error",
                        message=str(error),
                    ),
                ),
                build_fingerprint="vanilla-html-v1",
            )
        diagnostics: tuple[ProjectDiagnostic, ...] = ()
        sites: tuple[MountDeclaration, ...] = ()
        input_scope = (
            ProjectInput(PurePosixPath("view.toml"), "file"),
            ProjectInput(entry_path, "file"),
        )
        try:
            entry_document = _entry_document(project, entry_path)
            guidance_documents = _guidance_documents(project)
        except ConfigurationError as error:
            return ProjectInspection(
                editor_documents=(),
                input_scope=input_scope,
                mounts=(),
                diagnostics=(
                    ProjectDiagnostic(
                        code="entry-document-invalid",
                        severity="error",
                        message=str(error),
                        hint=(
                            "Restore the HTML entry document and build the view again."
                        ),
                    ),
                ),
                build_fingerprint=f"vanilla-html-v1:{entry_path.as_posix()}",
            )
        try:
            content = project.root.joinpath(*entry_path.parts).read_text(
                encoding="utf-8"
            )
            sites, _ = _mounts(entry_path, content)
        except HTMLLocalResourceError as error:
            diagnostics = (
                ProjectDiagnostic(
                    code="local-resource-unsupported",
                    severity="error",
                    message=str(error),
                    hint=(
                        "Inline the resource or create another view with a "
                        "provider for multi-file projects."
                    ),
                    source=SourceLocation(
                        entry_path,
                        error.line or 1,
                        error.column or 1,
                    ),
                ),
            )
        except (ConfigurationError, OSError, UnicodeError, ValueError) as error:
            line = error.line if isinstance(error, ViewProjectError) else None
            column = error.column if isinstance(error, ViewProjectError) else None
            hint = (
                error.public_hint
                if isinstance(error, ViewProjectError)
                else "Restore the HTML entry document and build the view again."
            )
            source = (
                SourceLocation(entry_path, line or 1, column or 1)
                if entry_document.path == entry_path
                else None
            )
            diagnostics = (
                ProjectDiagnostic(
                    code="entry-document-invalid",
                    severity="error",
                    message=str(error),
                    hint=hint,
                    source=source,
                ),
            )
        return ProjectInspection(
            editor_documents=(
                entry_document,
                *guidance_documents,
            ),
            input_scope=input_scope,
            mounts=sites,
            diagnostics=diagnostics,
            build_fingerprint=f"vanilla-html-v1:{entry_path.as_posix()}",
        )

    def build(self, request: BuildRequest) -> BuildResult:
        source_entry = _entry_path(request.project)
        reject_mutable_symlinks(
            request.project.root,
            {request.project.root.joinpath(*source_entry.parts)},
        )
        output = request.staging_root
        if request.cancellation.cancelled:
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        code="build-cancelled",
                        severity="error",
                        message="The Vanilla build was cancelled.",
                    ),
                ),
            )
        source = request.project.root.joinpath(*source_entry.parts)
        document = output.joinpath(*source_entry.parts)
        document.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, document)
        content = document.read_text(encoding="utf-8")
        instrumented = _instrument(
            source_entry,
            content,
            request.inspection.mounts,
        )
        if request.cancellation.cancelled:
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        code="build-cancelled",
                        severity="error",
                        message="The Vanilla build was cancelled.",
                    ),
                ),
            )
        document.write_text(instrumented, encoding="utf-8")
        return BuildResult(source_entry, ())


provider = VanillaProvider()
