"""Analyze the complete source graph for one Vanilla view snapshot."""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote_to_bytes, urlsplit

from marimo_studio._filesystem.budgets import (
    PROJECT_INPUT_BUDGET,
    FileBudgetTracker,
)
from marimo_studio._filesystem.io import read_bytes, reject_mutable_symlinks
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectInput,
    ProjectionKind,
    SourceDocument,
    SourceLocation,
    ViewProject,
    mount_attribute,
)
from marimo_studio.view_providers._css_resources import css_resource_urls
from marimo_studio.view_providers._document import (
    HTMLDocumentParser,
    HTMLInlineScript,
    HTMLLocalResourceError,
    HTMLResource,
    is_local_resource_url,
    validate_html_document,
)
from marimo_studio.view_providers._javascript import (
    TRUNCATED_SPECIFIER,
    JavaScriptDependency,
    javascript_dependencies,
)
from marimo_studio.view_providers._validation import validate_relative_path

_PROVIDER_KEY = "marimo-studio/vanilla"
_SOURCE_REVISION_ATTRIBUTE = "data-marimo-studio-source-revision"
_DEPENDENCY_HINT = (
    "Bundle or inline this dependency, use an explicit HTTPS, data, or fragment "
    "URL, or choose a provider that builds the source graph."
)
_ANALYSIS_ERRORS = (ConfigurationError, OSError, ValueError)


class VanillaLocalDependencyError(ViewProjectError):
    """A direct Vanilla source can fetch an undeclared project-local file."""


class VanillaSourceGraphError(Exception):
    """Preserve discovered source context when graph analysis fails."""

    def __init__(
        self,
        cause: Exception,
        *,
        mounts: tuple[MountDeclaration, ...],
        direct_documents: tuple[SourceDocument, ...],
        inputs: tuple[ProjectInput, ...],
    ) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.mounts = mounts
        self.direct_documents = direct_documents
        self.inputs = inputs


@dataclass(frozen=True)
class _Source:
    document: SourceDocument
    content: str
    sha256: str


@dataclass(frozen=True)
class _ResourceEdge:
    declaration: HTMLResource
    document: SourceDocument


@dataclass(frozen=True)
class _ParsedEntry:
    content: str
    mounts: tuple[MountDeclaration, ...]
    mount_offsets: tuple[int, ...]
    resources: tuple[HTMLResource, ...]
    inline_scripts: tuple[HTMLInlineScript, ...]


@dataclass(frozen=True)
class VanillaSourceGraph:
    """One validated entry document and its direct leaf sources."""

    entry: SourceDocument
    entry_content: str
    mounts: tuple[MountDeclaration, ...]
    direct_documents: tuple[SourceDocument, ...]
    inputs: tuple[ProjectInput, ...]
    resource_edges: tuple[_ResourceEdge, ...]
    javascript_revisions: tuple[tuple[PurePosixPath, str], ...]
    _mount_offsets: tuple[int, ...]

    @classmethod
    def analyze(
        cls,
        project: ViewProject,
        entry: SourceDocument,
        *,
        available_inputs: Collection[PurePosixPath] | None = None,
    ) -> VanillaSourceGraph:
        """Read and validate the source graph from one project snapshot."""
        inputs = cls.inputs_for(entry.path)
        try:
            parsed = _parse_entry(project, entry.path)
        except _ANALYSIS_ERRORS as error:
            raise VanillaSourceGraphError(
                error,
                mounts=(),
                direct_documents=(),
                inputs=inputs,
            ) from error

        try:
            _validate_inline_dependencies(entry.path, parsed.inline_scripts)
            resource_edges = tuple(
                _ResourceEdge(resource, _local_source_document(entry.path, resource))
                for resource in parsed.resources
            )
        except _ANALYSIS_ERRORS as error:
            raise VanillaSourceGraphError(
                error,
                mounts=parsed.mounts,
                direct_documents=(),
                inputs=inputs,
            ) from error

        validation_edges = _unique_resource_edges(resource_edges)
        direct_documents = tuple(edge.document for edge in validation_edges)
        inputs = cls.inputs_for(entry.path, direct_documents)
        try:
            if available_inputs is not None:
                _require_source_inputs(
                    inputs,
                    available_inputs,
                )
            revisions = _validate_direct_sources(
                project,
                entry.path,
                validation_edges,
            )
        except _ANALYSIS_ERRORS as error:
            raise VanillaSourceGraphError(
                error,
                mounts=parsed.mounts,
                direct_documents=direct_documents,
                inputs=inputs,
            ) from error

        return cls(
            entry=entry,
            entry_content=parsed.content,
            mounts=parsed.mounts,
            direct_documents=direct_documents,
            inputs=inputs,
            resource_edges=resource_edges,
            javascript_revisions=revisions,
            _mount_offsets=parsed.mount_offsets,
        )

    @staticmethod
    def inputs_for(
        entry: PurePosixPath,
        direct_documents: tuple[SourceDocument, ...] = (),
    ) -> tuple[ProjectInput, ...]:
        """Return the exact provider inputs discovered for an entry document."""
        return (
            ProjectInput(PurePosixPath("view.toml"), "file"),
            ProjectInput(entry, "file"),
            *(ProjectInput(item.path, "file") for item in direct_documents),
        )

    @property
    def editor_documents(self) -> tuple[SourceDocument, ...]:
        return (self.entry, *self.direct_documents)

    @property
    def source_paths(self) -> tuple[PurePosixPath, ...]:
        return (self.entry.path, *(item.path for item in self.direct_documents))

    def instrument(self, expected_mounts: tuple[MountDeclaration, ...]) -> str:
        """Add stable mount and JavaScript revision identities to the entry."""
        if self.mounts != expected_mounts:
            raise ValueError(
                "Vanilla projection sites changed before the build started"
            )
        revisions = dict(self.javascript_revisions)
        insertions: list[tuple[int, str]] = []
        for mount, offset in zip(self.mounts, self._mount_offsets, strict=True):
            name, value = mount_attribute(mount.id)
            insertions.append((offset, f' {name}="{value}"'))
        for edge in self.resource_edges:
            revision = revisions.get(edge.document.path)
            if revision is None:
                continue
            offset = edge.declaration.insertion_offset
            if offset is None:
                raise ValueError(
                    "Vanilla could not locate the script reference for "
                    f"{edge.document.path}"
                )
            insertions.append((offset, f' {_SOURCE_REVISION_ATTRIBUTE}="{revision}"'))
        return _insert_attributes(self.entry.path, self.entry_content, insertions)


def vanilla_entry_path(project: ViewProject) -> PurePosixPath:
    """Resolve the configured Vanilla HTML entry document."""
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


def vanilla_entry_document(
    project: ViewProject,
    entry: PurePosixPath,
) -> SourceDocument:
    """Validate and return the editable Vanilla entry document."""
    absolute_entry = project.root.joinpath(*entry.parts)
    reject_mutable_symlinks(project.root, {absolute_entry})
    if not absolute_entry.is_file():
        raise ConfigurationError(f"Vanilla entry document is unavailable: {entry}")
    return SourceDocument(entry, "html", "edit")


def _parse_entry(project: ViewProject, path: PurePosixPath) -> _ParsedEntry:
    content = _entry_content(project, path)
    parser = HTMLDocumentParser()
    parser.feed(content)
    validate_html_document(parser, path.as_posix())
    _validate_entry_contract(parser, path)
    mounts, offsets = _mounts(path, parser)
    return _ParsedEntry(
        content,
        mounts,
        offsets,
        tuple(parser.local_resources),
        tuple(parser.inline_scripts),
    )


def _validate_entry_contract(
    parser: HTMLDocumentParser,
    path: PurePosixPath,
) -> None:
    if parser.projection_outside_shell:
        raise ValueError(f"{path}: projection hosts must be inside #app-shell")
    if parser.has_reserved_runtime_markup:
        raise ValueError(f"{path}: source contains reserved runtime markup")
    _reject_parser_site(
        parser.import_map_position,
        "Vanilla import maps cannot preserve the direct-source allowlist",
        path,
        hint=(
            "Use explicit remote module URLs or choose a provider that builds "
            "the JavaScript module graph."
        ),
    )
    _reject_parser_site(
        parser.base_href_position,
        "Vanilla entry documents cannot set <base href>",
        path,
        hint=(
            "Resolve direct CSS and JavaScript paths relative to the HTML entry "
            "document."
        ),
    )
    _reject_parser_site(
        parser.authored_mount_declaration_position,
        "data-marimo-studio-site is reserved for Studio",
        path,
    )
    _reject_parser_site(
        parser.authored_source_revision_position,
        f"{_SOURCE_REVISION_ATTRIBUTE} is reserved for Studio",
        path,
    )


def _reject_parser_site(
    position: tuple[int, int] | None,
    message: str,
    path: PurePosixPath,
    *,
    hint: str | None = None,
) -> None:
    if position is None:
        return
    line, column = position
    raise ViewProjectError(
        message,
        source=path.as_posix(),
        line=line,
        column=column,
        hint=hint,
    )


def _mounts(
    path: PurePosixPath,
    parser: HTMLDocumentParser,
) -> tuple[tuple[MountDeclaration, ...], tuple[int, ...]]:
    mounts: list[MountDeclaration] = []
    offsets: list[int] = []
    occurrences: dict[tuple[ProjectionKind, str], int] = {}
    for kind in ("cell", "output", "value"):
        for declaration in parser.mounts:
            if declaration.kind != kind:
                continue
            key = (declaration.kind, declaration.target)
            occurrence = occurrences.get(key, 0)
            mounts.append(
                _literal_mount(
                    path,
                    declaration.kind,
                    declaration.target,
                    declaration.position,
                    occurrence,
                )
            )
            offsets.append(declaration.insertion_offset)
            occurrences[key] = occurrence + 1
    return tuple(mounts), tuple(offsets)


def _literal_mount(
    path: PurePosixPath,
    kind: ProjectionKind,
    target: str,
    position: tuple[int, int],
    occurrence: int,
) -> MountDeclaration:
    identity = json.dumps(
        [_PROVIDER_KEY, path.as_posix(), kind, target, occurrence],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    line, column = position
    return MountDeclaration(
        id=f"site-{hashlib.sha256(identity.encode()).hexdigest()}",
        kind=kind,
        source=SourceLocation(path, line, column),
        allowed_targets=(target,),
    )


def _entry_content(project: ViewProject, entry: PurePosixPath) -> str:
    path = project.root.joinpath(*entry.parts)
    try:
        return read_bytes(path, root=project.root).decode("utf-8")
    except UnicodeError as error:
        raise ConfigurationError(
            f"Vanilla entry document must be readable UTF-8 text: {entry}"
        ) from error


def _resource_error(
    entry: PurePosixPath,
    resource: HTMLResource,
    message: str,
) -> HTMLLocalResourceError:
    line, column = resource.position
    return HTMLLocalResourceError(
        f"{entry}: {message}",
        source=entry.as_posix(),
        line=line,
        column=column,
    )


def _local_source_document(
    entry: PurePosixPath,
    resource: HTMLResource,
) -> SourceDocument:
    parsed = urlsplit(resource.value)
    try:
        url_path = unquote_to_bytes(parsed.path).decode("utf-8")
    except UnicodeError as error:
        raise _resource_error(
            entry,
            resource,
            f"local resource {resource.value!r} has an invalid UTF-8 path",
        ) from error
    resolved = posixpath.normpath(posixpath.join(entry.parent.as_posix(), url_path))
    try:
        path = validate_relative_path(
            resolved,
            field=f"Vanilla local resource {resource.value!r}",
        )
    except ValueError as error:
        raise _resource_error(entry, resource, str(error)) from error
    return _resource_document(entry, resource, path)


def _resource_document(
    entry: PurePosixPath,
    resource: HTMLResource,
    path: PurePosixPath,
) -> SourceDocument:
    suffix = path.suffix.casefold()
    if (
        resource.tag == "link"
        and resource.attribute == "href"
        and "stylesheet" in resource.relations
        and suffix == ".css"
    ):
        return SourceDocument(path, "css", "edit")
    if (
        resource.tag == "script"
        and resource.attribute == "src"
        and suffix in {".js", ".mjs"}
    ):
        return SourceDocument(path, "javascript", "edit")
    raise _resource_error(
        entry,
        resource,
        (
            "project-local resources must be CSS from "
            "<link rel=stylesheet href> or JavaScript from <script src>. "
            f"received {resource.value!r} from "
            f"<{resource.tag} {resource.attribute}>"
        ),
    )


def _unique_resource_edges(
    resource_edges: tuple[_ResourceEdge, ...],
) -> tuple[_ResourceEdge, ...]:
    unique: dict[PurePosixPath, _ResourceEdge] = {}
    for edge in resource_edges:
        unique.setdefault(edge.document.path, edge)
    return tuple(unique.values())


def _require_source_inputs(
    inputs: tuple[ProjectInput, ...],
    available_inputs: Collection[PurePosixPath],
) -> None:
    required = {item.path for item in inputs}
    missing = sorted(required - set(available_inputs), key=str)
    if missing:
        raise ValueError(f"Vanilla build input is unavailable: {missing[0]}")


def _validate_direct_sources(
    project: ViewProject,
    entry: PurePosixPath,
    resource_edges: tuple[_ResourceEdge, ...],
) -> tuple[tuple[PurePosixPath, str], ...]:
    budget = FileBudgetTracker(PROJECT_INPUT_BUDGET, "Vanilla local sources")
    budget.require_count(len(resource_edges))
    revisions: list[tuple[PurePosixPath, str]] = []
    for edge in resource_edges:
        source = _read_source(project, entry, edge, budget)
        _validate_source_dependencies(source)
        if source.document.language == "javascript":
            revisions.append((source.document.path, source.sha256))
    return tuple(revisions)


def _read_source(
    project: ViewProject,
    entry: PurePosixPath,
    edge: _ResourceEdge,
    budget: FileBudgetTracker,
) -> _Source:
    path = project.root.joinpath(*edge.document.path.parts)
    try:
        payload = read_bytes(path, root=project.root)
        content = payload.decode("utf-8")
    except FileNotFoundError as error:
        raise _resource_error(
            entry,
            edge.declaration,
            f"local source is unavailable: {edge.document.path}",
        ) from error
    except ConfigurationError as error:
        raise _resource_error(entry, edge.declaration, str(error)) from error
    except (OSError, UnicodeError) as error:
        raise _resource_error(
            entry,
            edge.declaration,
            f"local source must be readable UTF-8 text: {edge.document.path}",
        ) from error
    try:
        budget.add(edge.document.path.as_posix(), len(payload))
    except ConfigurationError as error:
        raise _resource_error(entry, edge.declaration, str(error)) from error
    return _Source(
        edge.document,
        content,
        hashlib.sha256(payload).hexdigest(),
    )


def _validate_inline_dependencies(
    entry: PurePosixPath,
    scripts: tuple[HTMLInlineScript, ...],
) -> None:
    for script in scripts:
        for dependency in javascript_dependencies(script.content):
            message = _javascript_dependency_message_or_error(dependency)
            if message is None:
                continue
            line, column = _inline_source_position(script, dependency.offset)
            raise VanillaLocalDependencyError(
                f"{entry}: {message}",
                source=entry.as_posix(),
                line=line,
                column=column,
                hint=_DEPENDENCY_HINT,
            )


def _validate_source_dependencies(source: _Source) -> None:
    if source.document.language == "css":
        for value, offset in css_resource_urls(source.content):
            if _is_local_dependency(source, value, offset):
                raise _dependency_error(
                    source,
                    offset,
                    f"local CSS dependency {_dependency_label(value)} "
                    "is outside the artifact allowlist",
                )
        return
    for dependency in javascript_dependencies(source.content):
        message = _javascript_dependency_message_or_error(dependency)
        if message is not None:
            raise _dependency_error(source, dependency.offset, message)


def _javascript_dependency_message_or_error(
    dependency: JavaScriptDependency,
) -> str | None:
    try:
        return _javascript_dependency_message(dependency)
    except ValueError as error:
        return (
            "dependency URL "
            f"{_dependency_label(dependency.specifier or '')} "
            f"is invalid: {error}"
        )


def _javascript_dependency_message(
    dependency: JavaScriptDependency,
) -> str | None:
    if dependency.kind == "source import":
        return (
            "source-phase imports are outside the artifact allowlist and "
            "require a provider that builds the JavaScript module graph"
        )
    if dependency.kind == "parse error":
        return "JavaScript source contains syntax the dependency check cannot parse"
    if dependency.specifier == TRUNCATED_SPECIFIER:
        return (
            f"{dependency.kind} module specifier exceeds the "
            "4096-character inspection limit"
        )
    if dependency.specifier is None:
        if dependency.kind == "dynamic import":
            return (
                "computed dynamic import cannot be checked against the "
                "artifact allowlist"
            )
        return (
            f"{dependency.kind} module specifier cannot be checked against "
            "the artifact allowlist"
        )
    if not is_local_resource_url(dependency.specifier):
        return None
    return (
        f"local JavaScript {dependency.kind} "
        f"{_dependency_label(dependency.specifier)} "
        "is outside the artifact allowlist"
    )


def _is_local_dependency(source: _Source, value: str, offset: int) -> bool:
    try:
        return is_local_resource_url(value)
    except ValueError as error:
        raise _dependency_error(
            source,
            offset,
            f"dependency URL {_dependency_label(value)} is invalid: {error}",
        ) from error


def _dependency_error(
    source: _Source,
    offset: int,
    message: str,
) -> VanillaLocalDependencyError:
    line, column = _source_position(source.content, offset)
    return VanillaLocalDependencyError(
        f"{source.document.path}: {message}",
        source=source.document.path.as_posix(),
        line=line,
        column=column,
        hint=_DEPENDENCY_HINT,
    )


def _dependency_label(value: str) -> str:
    selected = value if len(value) <= 200 else f"{value[:197]}..."
    return repr(selected)


def _inline_source_position(
    script: HTMLInlineScript,
    offset: int,
) -> tuple[int, int]:
    relative_line, relative_column = _source_position(script.content, offset)
    if relative_line == 1:
        return script.position[0], script.position[1] + relative_column - 1
    return script.position[0] + relative_line - 1, relative_column


def _source_position(source: str, offset: int) -> tuple[int, int]:
    line = 1
    column = 1
    index = 0
    while index < offset:
        character = source[index]
        if character == "\r":
            if source[index : index + 2] == "\r\n":
                index += 1
            line += 1
            column = 1
        elif character in "\n\u2028\u2029":
            line += 1
            column = 1
        else:
            column += 1
        index += 1
    return line, column


def _insert_attributes(
    path: PurePosixPath,
    content: str,
    insertions: list[tuple[int, str]],
) -> str:
    source = content.encode("utf-8")
    parts: list[bytes] = []
    cursor = 0
    for offset, addition in sorted(insertions, key=lambda item: item[0]):
        if offset < cursor or offset > len(source):
            raise ValueError(f"Invalid Vanilla instrumentation offset in {path}")
        parts.extend((source[cursor:offset], addition.encode()))
        cursor = offset
    parts.append(source[cursor:])
    return b"".join(parts).decode("utf-8")
