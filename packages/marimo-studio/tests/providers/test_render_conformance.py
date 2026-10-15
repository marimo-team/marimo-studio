"""Check the renders a provider declares and the files its render() returns."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    BuildInput,
    ProjectDiagnostic,
    ProjectInspection,
    ProjectionSite,
    ProviderCancellation,
    Render,
    RenderCell,
    RenderFile,
    RenderOutput,
    RenderRequest,
    RenderResult,
    RenderValue,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import ProviderStub, candidate, inspection

PAGE = PurePosixPath("index.html")
TEMPLATE = PurePosixPath("report.typ")
SLIDES = PurePosixPath("slides.typ")
PDF = PurePosixPath("report.pdf")


def _at(line: int) -> SourceLocation:
    return SourceLocation(PAGE, line, 1)


def _figure(line: int, accept: tuple[str, ...]) -> RenderOutput:
    return RenderOutput("chart", _at(line), accept)


class RenderingStub(ProviderStub):
    """Declare ``renders`` and return ``result`` from render()."""

    def __init__(self) -> None:
        super().__init__("example/report", "default")
        self.result: object = RenderResult()
        self.files: dict[PurePosixPath, bytes] = {}
        self.links: dict[PurePosixPath, str] = {}

    def render(self, request: RenderRequest) -> RenderResult:
        for path, content in self.files.items():
            target = request.output_root.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for path, source in self.links.items():
            request.output_root.joinpath(*path.parts).symlink_to(source)
        return cast(RenderResult, self.result)


def _installed(provider: RenderingStub) -> Any:
    registry = ProviderRegistry((candidate("report", provider),))
    return registry.get(registry.ids[0])


def _inspect(tmp_path: Path, renders: object, *, sites: object = ()) -> Any:
    provider = RenderingStub()
    provider.inspection = replace(
        inspection(),
        inputs=tuple(BuildInput(path, "file") for path in (PAGE, TEMPLATE, SLIDES)),
        renders=cast(Any, renders),
        sites=cast(Any, sites),
    )
    installed = _installed(provider)
    project = ViewProject(
        "dashboard", tmp_path, tmp_path / "view.toml", installed.key, {}
    )
    return installed.inspect(inspection_request(project))


def _conflicts(inspected: ProjectInspection) -> list[ProjectDiagnostic]:
    return [
        item for item in inspected.diagnostics if item.code == "output-accept-conflict"
    ]


@pytest.mark.parametrize("source", ("../report.typ", "/report.typ", ""))
def test_render_sources_are_normalized_project_paths(
    tmp_path: Path, source: str
) -> None:
    with pytest.raises(
        ConfigurationError,
        match="render source must be a normalized project-relative POSIX path",
    ):
        _inspect(tmp_path, (Render(PurePosixPath(source)),))


def test_render_sources_are_posix_paths(tmp_path: Path) -> None:
    with pytest.raises(
        ConfigurationError, match="requires render source to be a PurePosixPath"
    ):
        _inspect(tmp_path, (Render(cast(Any, "report.typ")),))


def test_a_render_source_lies_within_the_build_inputs(tmp_path: Path) -> None:
    with pytest.raises(
        ConfigurationError,
        match=r"declares a render in 'notes\.typ' outside its build inputs",
    ):
        _inspect(tmp_path, (Render(PurePosixPath("notes.typ")),))


def test_each_render_source_is_declared_once(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="unique render sources"):
        _inspect(tmp_path, (Render(TEMPLATE), Render(TEMPLATE)))


def test_renders_are_render_records(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="requires Render records"):
        _inspect(tmp_path, ("report",))


def test_inspection_keeps_the_reads_of_each_render(tmp_path: Path) -> None:
    report = Render(
        TEMPLATE,
        values=(RenderValue("summary", _at(1)),),
        outputs=(_figure(2, ("application/pdf",)),),
    )
    slides = Render(SLIDES, cells=(RenderCell("plot", _at(3), ("image/png",)),))

    inspected = _inspect(tmp_path, (report, slides))

    assert inspected.renders == (report, slides)
    assert inspected.diagnostics == ()


def test_reads_of_one_target_in_one_render_accept_the_same_media_types(
    tmp_path: Path,
) -> None:
    render = Render(
        TEMPLATE,
        outputs=(_figure(1, ("application/pdf",)), _figure(2, ("image/png",))),
    )

    (conflict,) = _conflicts(_inspect(tmp_path, (render,)))

    assert conflict.source == _at(2)
    assert conflict.message == (
        "chart is read as image/png here and as application/pdf at index.html:1."
    )
    assert conflict.hint == (
        "Give every read of one output in the render of report.typ "
        "the same accept list."
    )


def test_a_page_host_and_renders_may_read_one_target_in_different_forms(
    tmp_path: Path,
) -> None:
    host = ProjectionSite("output", ("chart",), _at(1), 0, ("image/png",))
    renders = (
        Render(TEMPLATE, outputs=(_figure(2, ("application/pdf",)),)),
        Render(SLIDES, outputs=(_figure(3, ("image/svg+xml",)),)),
    )

    assert _conflicts(_inspect(tmp_path, renders, sites=(host,))) == []


def _render(
    tmp_path: Path,
    result: object,
    *,
    files: dict[PurePosixPath, bytes] | None = None,
    links: dict[PurePosixPath, str] | None = None,
) -> RenderResult:
    provider = RenderingStub()
    provider.result = result
    provider.files = files if files is not None else {PDF: b"%PDF-1.7\n"}
    provider.links = links or {}
    template = tmp_path / "template"
    template.mkdir()
    template.joinpath(TEMPLATE).write_text("Report", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    cancellation = ProviderCancellation()
    return _installed(provider).render(
        RenderRequest(
            source=TEMPLATE,
            template_root=template,
            values={},
            outputs={},
            cells={},
            output_root=output,
            cancellation=cancellation,
            runner=create_provider_runner(template, cancellation, 10),
            command_timeout=10,
        )
    )


def test_a_render_returns_its_files_with_any_media_type(tmp_path: Path) -> None:
    video = PurePosixPath("media/report.mp4")
    poster = PurePosixPath("media/poster.png")
    files = (RenderFile(video, "video/mp4"), RenderFile(poster, "image/png"))

    result = _render(
        tmp_path,
        RenderResult(files, main=video, preview=poster),
        files={video: b"video", poster: b"poster"},
    )

    assert result == RenderResult(files, main=video, preview=poster)


def test_a_failed_render_returns_its_error_without_files(tmp_path: Path) -> None:
    error = ProjectDiagnostic("report-error", "error", "The report failed.")

    result = _render(
        tmp_path,
        RenderResult(
            (RenderFile(PDF, "application/pdf"),), main=PDF, diagnostics=(error,)
        ),
    )

    assert result == RenderResult(diagnostics=(error,))


_PDF_FILE = RenderFile(PDF, "application/pdf")


@pytest.mark.parametrize(
    ("result", "message"),
    (
        (RenderResult((_PDF_FILE,)), "rendered no main file or error diagnostic"),
        (
            RenderResult(
                (RenderFile(PurePosixPath("missing.pdf"), "application/pdf"),),
                main=PurePosixPath("missing.pdf"),
            ),
            "rendered no file at 'missing.pdf'",
        ),
        (
            RenderResult(
                (RenderFile(PurePosixPath("../report.pdf"), "application/pdf"),),
                main=PurePosixPath("../report.pdf"),
            ),
            "rendered file",
        ),
        (
            RenderResult((RenderFile(PDF, "PDF"),), main=PDF),
            "media type 'PDF'",
        ),
        (
            RenderResult((RenderFile(PDF, "application/pdf; version=1.7"),), main=PDF),
            "media type",
        ),
        (
            RenderResult((_PDF_FILE,), main=PurePosixPath("other.pdf")),
            "names main file 'other.pdf', which it did not list in files",
        ),
        (
            RenderResult((_PDF_FILE,), main=PDF, preview=PurePosixPath("poster.png")),
            "names preview file 'poster.png', which it did not list in files",
        ),
        (
            RenderResult((_PDF_FILE,), main=PDF, preview=PDF),
            "names the main file as its own preview",
        ),
        (
            RenderResult((_PDF_FILE, _PDF_FILE), main=PDF),
            "unique rendered file paths",
        ),
        ("report.pdf", "requires a RenderResult record"),
    ),
    ids=(
        "no-main",
        "missing-file",
        "escaping-path",
        "media-type-shape",
        "media-type-parameters",
        "main-not-listed",
        "preview-not-listed",
        "preview-is-main",
        "duplicate-files",
        "not-a-result",
    ),
)
def test_render_results_name_files_the_render_wrote(
    tmp_path: Path, result: object, message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        _render(tmp_path, result)


@pytest.mark.skipif(os.name == "nt", reason="creates a POSIX symlink")
def test_a_rendered_file_cannot_be_a_symlink(tmp_path: Path) -> None:
    link = PurePosixPath("link.pdf")

    with pytest.raises(ConfigurationError, match=r"rendered no file at 'link\.pdf'"):
        _render(
            tmp_path,
            RenderResult((RenderFile(link, "application/pdf"),), main=link),
            links={link: PDF.name},
        )
