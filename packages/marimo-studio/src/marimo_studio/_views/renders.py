"""Run one declared render and collect the files it publishes.

Studio renders a private copy of a view's template with the notebook results
one render reads. The provider lists the files it wrote, and Studio copies
exactly those into a bundle it owns. A bundle's ID is the digest of its files,
media types, roles, and regions, so identical output shares one bundle.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from marimo_export.wire import canonical_json_bytes, parse_canonical_json

from marimo_studio._filesystem.budgets import FileBudget, FileBudgetTracker
from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio._views.records import DiagnosticsError
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.errors._internal import ArtifactIntegrityError
from marimo_studio.view_providers import (
    JsonValue,
    ProjectDiagnostic,
    ProviderAvailability,
    ProviderCancellation,
    RenderRegion,
    RenderRequest,
    RenderResult,
    Representation,
)
from marimo_studio.view_providers._artifact_sites import ArtifactSite
from marimo_studio.view_providers._regions import admit_regions
from marimo_studio.view_providers._targets import MAX_RENDER_FILES

# A render may encode a video, so it runs longer than one compile.
RENDER_COMMAND_TIMEOUT = 300.0
# What one render reads: values as compact JSON, and outputs, such as several
# large figures, as bytes.
MAX_RENDER_VALUE_BYTES = 8 * 1024 * 1024
MAX_RENDER_MEDIA_BYTES = 16 * 1024 * 1024
RENDER_OUTPUT_BUDGET = FileBudget(
    max_files=MAX_RENDER_FILES,
    max_file_bytes=512 * 1024 * 1024,
    max_total_bytes=1024 * 1024 * 1024,
)
_COPY_CHUNK_BYTES = 1024 * 1024
_JSON_HINT = (
    "Read a table, a dictionary, a list, text, a number, or a date, or select "
    "one of its fields."
)


class Renderer(Protocol):
    key: str
    can_render: bool

    def availability(self) -> ProviderAvailability: ...

    def render(self, request: RenderRequest) -> RenderResult: ...


def _unavailable(renderer: Renderer) -> DiagnosticsError | None:
    """Explain a failed render by a missing provider requirement.

    A server can start without a provider's extra and still serve a view an
    earlier command built, so the first render is where the requirement shows.
    """
    availability = renderer.availability()
    if availability.available:
        return None
    detail = f": {availability.reason.rstrip('.')}" if availability.reason else ""
    return DiagnosticsError(
        (
            ProjectDiagnostic(
                "provider-unavailable",
                "error",
                f"View provider {renderer.key!r} is unavailable{detail}.",
                availability.action or "",
            ),
        )
    )


@dataclass(frozen=True)
class BundleFile:
    """One rendered file in a bundle, with its media type and content digest."""

    path: PurePosixPath
    media_type: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path.as_posix(),
            "mediaType": self.media_type,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class RenderBundle:
    """The immutable files one render published, stored beneath ``root``.

    ``regions`` locates the parts of those files that notebook results
    produced, and belongs to the bundle's identity.
    """

    id: str
    root: Path
    files: tuple[BundleFile, ...]
    main: PurePosixPath
    preview: PurePosixPath | None
    warnings: tuple[ProjectDiagnostic, ...]
    regions: tuple[RenderRegion, ...] = ()

    @property
    def size(self) -> int:
        return sum(item.size for item in self.files)

    def file(self, path: PurePosixPath) -> BundleFile | None:
        return next((item for item in self.files if item.path == path), None)

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle": self.id,
            "files": [item.to_dict() for item in self.files],
            "main": self.main.as_posix(),
            "preview": self.preview.as_posix() if self.preview is not None else None,
            "warnings": [item.to_dict() for item in self.warnings],
            "regions": [item.to_dict() for item in self.regions],
        }


def renderer_missing() -> ProjectDiagnostic:
    return ProjectDiagnostic(
        "renderer-missing",
        "error",
        "The view declares renders, and its provider has no render().",
        "Choose a provider that renders files from notebook results.",
    )


def value_not_json(target: str, problem: str) -> ProjectDiagnostic:
    """Report a render value that has no portable JSON form."""
    return ProjectDiagnostic(
        "render-value-not-json",
        "error",
        f"{target} has no JSON form: {problem.rstrip('.')}.",
        _JSON_HINT,
    )


def value_read_failure(code: str, message: str) -> ProjectDiagnostic:
    """Report a value the notebook computed that a render cannot read.

    ``code`` and ``message`` come from the runtime's value read, and the
    message names the target.
    """
    if code == "not-json-serializable":
        return ProjectDiagnostic("render-value-not-json", "error", message, _JSON_HINT)
    if code.endswith("too-large"):
        return ProjectDiagnostic(
            "render-values-too-large",
            "error",
            message,
            "Filter or aggregate the value in the notebook, or read one of its fields.",
        )
    return ProjectDiagnostic(
        "render-input-unavailable",
        "error",
        message,
        "Run the notebook again, then reload the page.",
    )


def read_accept(
    sites: tuple[ArtifactSite, ...], kind: str
) -> dict[str, tuple[str, ...]]:
    """Return the media types one render reads each target of ``kind`` in."""
    return {
        target: site.accept
        for site in sites
        if site.kind == kind
        for target in site.targets or ()
    }


def absent_reads(
    sites: tuple[ArtifactSite, ...],
    values: Mapping[str, object],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
) -> list[str]:
    """Return the targets one render reads that have no current result."""
    present = {"value": values, "output": outputs, "cell": cells}
    return sorted(
        target
        for site in sites
        for target in site.targets or ()
        if target not in present[site.kind]
    )


def canonical_values(
    values: Mapping[str, object],
) -> tuple[dict[str, JsonValue], bytes]:
    """Return render values as portable JSON data and its canonical bytes.

    Portable JSON spells numbers as JavaScript does, so a Python kernel, a
    browser runtime, and a prepared export that produce the same number render
    the same files and share one bundle.
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


class RenderInputError(ValueError):
    """A render names a target it does not read, or unaccepted media."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def admit_render_inputs(
    sites: tuple[ArtifactSite, ...],
    values: Mapping[str, object],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
) -> None:
    """Raise ``RenderInputError`` unless one render's ``sites`` read every input."""
    unknown = sorted(set(values) - set(read_accept(sites, "value")))
    for kind, media in (("output", outputs), ("cell", cells)):
        accept = read_accept(sites, kind)
        unknown.extend(sorted(set(media) - set(accept)))
        for target in sorted(set(media) & set(accept)):
            media_type = media[target].media_type
            if media_type not in accept[target]:
                raise RenderInputError(
                    f"render-{kind}-not-accepted",
                    f"The render reads {target!r} as {', '.join(accept[target])}, "
                    f"not {media_type}.",
                )
    if unknown:
        raise RenderInputError(
            "render-target-not-allowed", f"The render does not read {unknown[0]!r}."
        )


def render_key(
    source: PurePosixPath,
    encoded_values: bytes,
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
) -> bytes:
    """Return the digest that identifies one render's inputs."""
    digest = hashlib.sha256(f"{source.as_posix()}\0".encode())
    digest.update(encoded_values)
    for kind, media in (("output", outputs), ("cell", cells)):
        for target in sorted(media):
            item = media[target]
            fields = {**asdict(item), "data": hashlib.sha256(item.data).hexdigest()}
            digest.update(f"\0{kind}\0{target}\0".encode())
            digest.update(json.dumps(fields, sort_keys=True).encode())
    return digest.digest()


def _over_budget(code: str, kind: str, limit: int) -> DiagnosticsError:
    return DiagnosticsError(
        (
            ProjectDiagnostic(
                code,
                "error",
                f"The {kind} this render reads exceed {limit // 2**20} MiB.",
                f"Read fewer or smaller {kind} in the render.",
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
    if len(encoded.encode()) > MAX_RENDER_VALUE_BYTES:
        raise _over_budget("render-values-too-large", "values", MAX_RENDER_VALUE_BYTES)
    media = (*outputs.values(), *cells.values())
    if sum(len(item.data) for item in media) > MAX_RENDER_MEDIA_BYTES:
        raise _over_budget(
            "render-outputs-too-large", "outputs", MAX_RENDER_MEDIA_BYTES
        )


def _copy_file(file: Path, destination: Path) -> tuple[str, int]:
    """Copy one regular file and return its SHA-256 digest and byte size."""
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with file.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
            writer.write(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _bundle_id(
    files: tuple[BundleFile, ...],
    main: PurePosixPath,
    preview: PurePosixPath | None,
    regions: tuple[RenderRegion, ...],
) -> str:
    identity = {
        "files": [item.to_dict() for item in files],
        "main": main.as_posix(),
        "preview": preview.as_posix() if preview is not None else None,
        "regions": [item.to_dict() for item in regions],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def run_render(
    renderer: Renderer,
    copy_template: Callable[[Path], object],
    source: PurePosixPath,
    sites: tuple[ArtifactSite, ...],
    values: Mapping[str, JsonValue],
    outputs: Mapping[str, Representation],
    cells: Mapping[str, Representation],
    cancellation: ProviderCancellation,
    destination: Path,
) -> RenderBundle:
    """Render a private, writable copy of a template into ``destination``.

    ``sites`` are the render's read sites, which bound the reads its regions
    may name. ``copy_template`` writes the template into the directory it
    receives.
    ``destination`` must be absent, and receives exactly the files the render
    lists. Raises ``DiagnosticsError`` with the render diagnostics when the
    render fails or the template fails verification. A provider failure after
    cancellation propagates unchanged.
    """
    check_render_budget(values, outputs, cells)
    with tempfile.TemporaryDirectory(prefix="marimo-studio-render-") as scratch:
        template_root = Path(scratch, "template")
        output_root = Path(scratch, "output")
        output_root.mkdir()
        try:
            copy_template(template_root)
        except ArtifactIntegrityError as error:
            raise DiagnosticsError(
                (
                    ProjectDiagnostic(
                        error.code,
                        "error",
                        str(error),
                        "Rebuild the view, then reload the page.",
                    ),
                )
            ) from error
        try:
            result = renderer.render(
                RenderRequest(
                    source=source,
                    template_root=template_root,
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
            raise _unavailable(renderer) or DiagnosticsError(
                (
                    ProjectDiagnostic(
                        "render-failed",
                        "error",
                        str(error),
                        f"Fix {source}, or read fewer notebook results in it, "
                        "then save it to render again.",
                    ),
                )
            ) from error
        errors = tuple(item for item in result.diagnostics if item.severity == "error")
        if result.main is None or errors:
            raise _unavailable(renderer) or DiagnosticsError(
                errors
                or (
                    ProjectDiagnostic(
                        "render-failed",
                        "error",
                        f"The render of {source} produced no main file.",
                    ),
                )
            )
        regions, problems = admit_regions(
            result.regions,
            {item.path: item.media_type for item in result.files},
            sites,
        )
        tracker = FileBudgetTracker(RENDER_OUTPUT_BUDGET, f"The render of {source}")
        destination.mkdir()
        files: list[BundleFile] = []
        try:
            for item in result.files:
                cancellation.raise_if_cancelled("Collecting rendered files")
                file = output_root.joinpath(*item.path.parts)
                tracker.add(item.path.as_posix(), file.stat().st_size)
                digest, size = _copy_file(file, destination.joinpath(*item.path.parts))
                files.append(BundleFile(item.path, item.media_type, digest, size))
        except ConfigurationError as error:
            shutil.rmtree(destination, ignore_errors=True)
            raise DiagnosticsError(
                (
                    ProjectDiagnostic(
                        "render-too-large",
                        "error",
                        str(error),
                        "Render fewer or smaller files.",
                    ),
                )
            ) from error
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        ordered = tuple(sorted(files, key=lambda item: item.path.as_posix()))
        return RenderBundle(
            _bundle_id(ordered, result.main, result.preview, regions),
            destination,
            ordered,
            result.main,
            result.preview,
            (
                *(item for item in result.diagnostics if item.severity == "warning"),
                *problems,
            ),
            regions,
        )
