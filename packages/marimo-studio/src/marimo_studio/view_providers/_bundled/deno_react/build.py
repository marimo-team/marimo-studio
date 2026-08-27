"""Build an inspected React project into a Studio staging directory."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectDiagnostic,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.analysis import apply_instrumentation
from marimo_studio.view_providers._bundled._deno.project import (
    ProviderProjectSpec,
    command,
    copy_public_assets,
    failure,
)
from marimo_studio.view_providers._validation import validate_relative_path

_LABEL = "React provider"
_SCRIPT_SOURCE = re.compile(
    r"(?:^|\s)src\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|"
    r"(?P<bare>[^\s\"'=<>`]+))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ScriptReference:
    start: int
    end: int
    value: str


class _ScriptParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._source = source
        self._line_offsets = [0]
        self._line_offsets.extend(
            index + 1 for index, character in enumerate(source) if character == "\n"
        )
        self.references: list[_ScriptReference] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "script":
            return
        sources = [value for name, value in attrs if name.casefold() == "src"]
        if not sources:
            return
        if len(sources) != 1 or sources[0] is None:
            raise ValueError("React build emitted an invalid script source")
        raw = self.get_starttag_text()
        if raw is None:
            raise ValueError("React build emitted an unreadable script tag")
        matches = tuple(_SCRIPT_SOURCE.finditer(raw))
        if len(matches) != 1:
            raise ValueError("React build emitted an ambiguous script source")
        match = matches[0]
        group = next(
            name
            for name in ("double", "single", "bare")
            if match.group(name) is not None
        )
        local_start, local_end = match.span(group)
        line, column = self.getpos()
        tag_start = self._line_offsets[line - 1] + column
        self.references.append(
            _ScriptReference(
                tag_start + local_start,
                tag_start + local_end,
                self._source[tag_start + local_start : tag_start + local_end],
            )
        )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)


def _boundary_diagnostic(
    code: str,
    message: str,
    path: PurePosixPath,
) -> ProjectDiagnostic:
    return ProjectDiagnostic(
        code=code,
        severity="error",
        message=message,
        source=SourceLocation(path, 1, 1),
    )


def _local_target_error(
    root: Path,
    base: Path,
    target: str,
    *,
    bare_local: bool = False,
) -> str | None:
    parsed = urlsplit(unescape(target))
    if parsed.scheme:
        if parsed.scheme.casefold() != "file":
            return None
        if parsed.netloc not in {"", "localhost"}:
            return f"Local file URL {target!r} is outside the view project"
        candidate = Path(url2pathname(unquote(parsed.path))).resolve(strict=False)
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return f"Local file URL {target!r} is outside the view project"
        return None
    path = parsed.path
    if not path:
        return None
    if bare_local and not path.startswith((".", "/", "\\")):
        path = f"./{path}"
    if not path.startswith((".", "/", "\\")):
        return None
    if Path(path).is_absolute() or re.match(r"^[a-zA-Z]:[\\/]", path):
        return f"Absolute module target {target!r} is outside the view project"
    candidate = (base / path).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return f"Module target {target!r} leaves the view project"
    return None


def react_project_diagnostics(project: ViewProject) -> tuple[ProjectDiagnostic, ...]:
    """Validate React configuration and HTML module paths without resolving them."""
    diagnostics: list[ProjectDiagnostic] = []
    try:
        entry = validate_relative_path(
            project.options.get("entrypoint", "src/index.html"),
            field="marimo-studio/react entrypoint",
        )
    except ValueError as error:
        return (
            _boundary_diagnostic(
                "provider-options-invalid",
                str(error),
                PurePosixPath("view.toml"),
            ),
        )
    if entry != PurePosixPath("src/index.html"):
        diagnostics.append(
            _boundary_diagnostic(
                "react-entrypoint-unsupported",
                "React entrypoint must be src/index.html",
                PurePosixPath("view.toml"),
            )
        )
    entry_path = project.root.joinpath(*entry.parts)
    if entry_path.is_file():
        try:
            source = entry_path.read_text(encoding="utf-8")
            parser = _ScriptParser(source)
            parser.feed(source)
            for reference in parser.references:
                error = _local_target_error(
                    project.root,
                    entry_path.parent,
                    reference.value,
                    bare_local=True,
                )
                if error is not None:
                    diagnostics.append(
                        _boundary_diagnostic(
                            "module-path-outside-project",
                            error,
                            entry,
                        )
                    )
        except (OSError, UnicodeError, ValueError) as error:
            diagnostics.append(
                _boundary_diagnostic(
                    "react-entry-document-invalid",
                    str(error),
                    entry,
                )
            )
    try:
        config = validate_relative_path(
            project.options.get("config", "deno.json"),
            field="marimo-studio/react config",
        )
    except ValueError as error:
        diagnostics.append(
            _boundary_diagnostic(
                "provider-options-invalid",
                str(error),
                PurePosixPath("view.toml"),
            )
        )
        return tuple(diagnostics)
    config_path = project.root.joinpath(*config.parts)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("React Deno config must contain a JSON object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        diagnostics.append(
            _boundary_diagnostic(
                "react-config-invalid",
                str(error),
                config,
            )
        )
        return tuple(diagnostics)
    for field in ("workspace", "links"):
        if field in payload:
            diagnostics.append(
                _boundary_diagnostic(
                    "react-project-boundary-invalid",
                    f"React Deno config cannot declare {field}",
                    config,
                )
            )
    compiler_options = payload.get("compilerOptions", {})
    if not isinstance(compiler_options, dict):
        diagnostics.append(
            _boundary_diagnostic(
                "react-config-invalid",
                "React compilerOptions must contain a JSON object",
                config,
            )
        )
        compiler_options = {}
    for field in ("jsxImportSource", "jsxImportSourceTypes"):
        target = compiler_options.get(field)
        if target is None:
            continue
        if not isinstance(target, str):
            diagnostics.append(
                _boundary_diagnostic(
                    "react-config-invalid",
                    f"React compilerOptions.{field} must be a string",
                    config,
                )
            )
            continue
        error = _local_target_error(project.root, config_path.parent, target)
        if error is not None:
            diagnostics.append(
                _boundary_diagnostic(
                    "module-path-outside-project",
                    error,
                    config,
                )
            )
    import_map = payload.get("importMap")
    if isinstance(import_map, str):
        error = _local_target_error(
            project.root,
            config_path.parent,
            import_map,
            bare_local=True,
        )
        if error is not None:
            diagnostics.append(
                _boundary_diagnostic(
                    "module-path-outside-project",
                    error,
                    config,
                )
            )
    targets: list[str] = []
    imports = payload.get("imports", {})
    if isinstance(imports, dict):
        targets.extend(value for value in imports.values() if isinstance(value, str))
    scopes = payload.get("scopes", {})
    if isinstance(scopes, dict):
        for values in scopes.values():
            if isinstance(values, dict):
                targets.extend(
                    value for value in values.values() if isinstance(value, str)
                )
    for target in targets:
        error = _local_target_error(project.root, config_path.parent, target)
        if error is not None:
            diagnostics.append(
                _boundary_diagnostic(
                    "module-path-outside-project",
                    error,
                    config,
                )
            )
    return tuple(diagnostics)


def _module_graph_diagnostics(
    project: ViewProject,
    work: Path,
    main: PurePosixPath,
    config: PurePosixPath,
    lockfile: PurePosixPath,
    execution: _deno.DenoExecution,
) -> tuple[ProjectDiagnostic, ...]:
    resolved, diagnostic = command(
        _LABEL,
        project,
        (
            "info",
            "--json",
            f"--config={work.joinpath(*config.parts)}",
            f"--lock={work.joinpath(*lockfile.parts)}",
            "--frozen",
            "--node-modules-dir=none",
            main.as_posix(),
        ),
        cwd=work,
        code="react-module-graph-failed",
        operation="resolve the source module graph",
        execution=execution,
        network_environment=True,
    )
    if diagnostic is not None:
        return (diagnostic,)
    assert resolved is not None
    if resolved.returncode != 0:
        return (
            failure(
                _LABEL,
                "react-module-graph-failed",
                "resolve the source module graph",
                resolved.stderr or resolved.stdout,
            ),
        )
    try:
        payload = json.loads(resolved.stdout)
        modules = payload["modules"]
        if not isinstance(modules, list):
            raise TypeError("modules must be a list")
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        return (
            _boundary_diagnostic(
                "react-module-graph-invalid",
                f"Deno returned an invalid module graph: {error}",
                main,
            ),
        )
    diagnostics: list[ProjectDiagnostic] = []
    snapshot_root = work.resolve()
    for module in modules:
        if not isinstance(module, dict):
            continue
        specifier = module.get("specifier")
        if not isinstance(specifier, str):
            continue
        parsed = urlsplit(specifier)
        if parsed.scheme.casefold() != "file":
            continue
        if parsed.netloc not in {"", "localhost"}:
            diagnostics.append(
                _boundary_diagnostic(
                    "module-path-outside-snapshot",
                    f"Local module {specifier!r} leaves the immutable view snapshot",
                    main,
                )
            )
            continue
        local = Path(url2pathname(unquote(parsed.path))).resolve()
        try:
            local.relative_to(snapshot_root)
        except ValueError:
            diagnostics.append(
                _boundary_diagnostic(
                    "module-path-outside-snapshot",
                    f"Local module {specifier!r} leaves the immutable view snapshot",
                    main,
                )
            )
    return tuple(diagnostics)


def _normalize_entry_name(output: Path) -> None:
    document_path = output / "index.html"
    document = document_path.read_text(encoding="utf-8")
    parser = _ScriptParser(document)
    parser.feed(document)
    referenced: list[tuple[_ScriptReference, Path, str]] = []
    for reference in parser.references:
        parsed = urlsplit(unescape(reference.value))
        if parsed.scheme or parsed.netloc or not parsed.path.endswith(".js"):
            continue
        try:
            relative = validate_relative_path(
                parsed.path.removeprefix("./"),
                field="React script source",
            )
        except ValueError:
            continue
        entry = output.joinpath(*relative.parts)
        if entry.is_file():
            referenced.append((reference, entry, parsed.path))
    if len(referenced) != 1:
        raise ValueError("React build must emit one referenced JavaScript entry")
    reference, entry, decoded_path = referenced[0]
    digest = hashlib.sha256(entry.read_bytes()).hexdigest()
    prefix = entry.stem.rsplit("-", 1)[0]
    normalized = entry.with_name(f"{prefix}-{digest}.js")
    if normalized.exists() and normalized != entry:
        raise ValueError(f"React entry output already exists: {normalized.name}")
    query_or_fragment = len(reference.value)
    for separator in ("?", "#"):
        candidate = reference.value.find(separator)
        if candidate >= 0:
            query_or_fragment = min(query_or_fragment, candidate)
    raw_path = reference.value[:query_or_fragment]
    if not decoded_path.endswith(entry.name) or not raw_path.endswith(entry.name):
        raise ValueError("React script source does not match its generated entry")
    replacement = (
        f"{raw_path[: -len(entry.name)]}{normalized.name}"
        f"{reference.value[query_or_fragment:]}"
    )
    document = document[: reference.start] + replacement + document[reference.end :]
    entry.replace(normalized)
    document_path.write_text(document, encoding="utf-8")


def _build_react(
    request: BuildRequest,
    spec: ProviderProjectSpec,
    execution: _deno.DenoExecution,
) -> BuildResult:
    """Check, instrument, and bundle one React project."""
    try:
        analysis = spec.analyze(
            request.project,
            request.inspection,
            execution,
        )
    except ValueError as error:
        return BuildResult(
            None,
            (
                ProjectDiagnostic(
                    code="provider-options-invalid",
                    severity="error",
                    message=str(error),
                ),
            ),
        )
    if analysis.diagnostics:
        return BuildResult(None, analysis.diagnostics)
    if analysis.sites != request.inspection.mounts:
        return BuildResult(
            None,
            (
                ProjectDiagnostic(
                    code="projection-sites-changed",
                    severity="error",
                    message="React projection sites changed before the build started.",
                ),
            ),
        )
    work = request.staging_root.parent / "work"
    try:
        _deno.copy_project_inputs(
            request.project,
            request.inputs,
            work,
            request.cancellation,
        )
        main = validate_relative_path(
            request.project.options.get("main", "src/main.tsx"),
            field="React main",
        )
        entrypoint = validate_relative_path(
            request.project.options.get("entrypoint", "src/index.html"),
            field="React entrypoint",
        )
        config = validate_relative_path(
            request.project.options.get("config", "deno.json"),
            field="React Deno config",
        )
        lockfile = validate_relative_path(
            request.project.options.get("lockfile", "deno.lock"),
            field="React lockfile",
        )
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (failure(_LABEL, "react-staging-failed", "stage source", str(error)),),
        )
    graph_diagnostics = _module_graph_diagnostics(
        request.project,
        work,
        main,
        config,
        lockfile,
        execution,
    )
    if graph_diagnostics:
        return BuildResult(None, graph_diagnostics)
    checked, diagnostic = command(
        _LABEL,
        request.project,
        (
            "check",
            f"--config={work.joinpath(*config.parts)}",
            f"--lock={work.joinpath(*lockfile.parts)}",
            "--frozen",
            "--node-modules-dir=none",
            main.as_posix(),
        ),
        cwd=work,
        code="react-check-failed",
        operation="type-check source",
        execution=execution,
        network_environment=True,
    )
    if diagnostic is not None:
        return BuildResult(None, (diagnostic,))
    assert checked is not None
    if checked.returncode != 0:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "react-check-failed",
                    "type-check source",
                    checked.stderr,
                ),
            ),
        )
    try:
        apply_instrumentation(work, analysis.edits)
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "react-instrumentation-failed",
                    "instrument projection sites",
                    str(error),
                ),
            ),
        )
    arguments = [
        "bundle",
        f"--config={work.joinpath(*config.parts)}",
        f"--lock={work.joinpath(*lockfile.parts)}",
        "--frozen",
        "--node-modules-dir=none",
        "--platform=browser",
        "--packages=bundle",
        f"--outdir={request.staging_root}",
    ]
    arguments.append(
        "--sourcemap=inline" if request.profile == "development" else "--minify"
    )
    arguments.append(entrypoint.name)
    bundled, diagnostic = command(
        _LABEL,
        request.project,
        arguments,
        cwd=work.joinpath(*entrypoint.parent.parts),
        code="react-build-failed",
        operation="bundle source",
        execution=execution,
        network_environment=True,
    )
    if diagnostic is not None:
        return BuildResult(None, (diagnostic,))
    assert bundled is not None
    if bundled.returncode != 0:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "react-build-failed",
                    "bundle source",
                    bundled.stderr,
                ),
            ),
        )
    try:
        _normalize_entry_name(request.staging_root)
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "react-output-invalid",
                    "normalize browser output",
                    str(error),
                ),
            ),
        )
    try:
        copy_public_assets(
            work,
            request.staging_root,
            cancellation=request.cancellation,
        )
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "react-public-assets-invalid",
                    "publish public assets",
                    str(error),
                ),
            ),
        )
    return BuildResult(PurePosixPath("index.html"), ())


def build_react(
    request: BuildRequest,
    spec: ProviderProjectSpec,
) -> BuildResult:
    """Check, instrument, and bundle one React project."""
    boundary_diagnostics = react_project_diagnostics(request.project)
    if boundary_diagnostics:
        return BuildResult(None, boundary_diagnostics)
    try:
        execution = _deno.create_execution(
            request.project,
            cache_root=request.cache_root,
            cancellation=request.cancellation,
            runner=request.runner,
        )
        return _build_react(request, spec, execution)
    except _deno.DenoExecutionError as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "react-build-failed",
                    "finish the build",
                    str(error),
                ),
            ),
        )
