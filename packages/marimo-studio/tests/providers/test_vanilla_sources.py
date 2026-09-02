from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers._bundled.vanilla import provider

from ..provider_test_support import provider_build_request
from ._vanilla_test_support import _project


def test_vanilla_publishes_direct_local_css_and_javascript(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            """<link rel="stylesheet" href="./styles/app.css?theme=dark" />
            <script type="module" src="./scripts/app.js#boot"></script>
            </head>""",
        ),
        encoding="utf-8",
    )
    styles = project.root / "styles" / "app.css"
    script = project.root / "scripts" / "app.js"
    styles.parent.mkdir()
    script.parent.mkdir()
    styles.write_text("body { color: rebeccapurple; }\n", encoding="utf-8")
    script.write_text(
        'document.documentElement.dataset.localScript = "ready";\n',
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "multi-file" / "files"
    files.mkdir(parents=True)
    report = provider.build(provider_build_request(project, inspection, files))

    assert inspection.diagnostics == ()
    assert [item.to_dict() for item in inspection.editor_documents] == [
        {
            "path": "index.html",
            "language": "html",
            "access": "edit",
            "label": None,
        },
        {
            "path": "styles/app.css",
            "language": "css",
            "access": "edit",
            "label": None,
        },
        {
            "path": "scripts/app.js",
            "language": "javascript",
            "access": "edit",
            "label": None,
        },
        {
            "path": "AGENTS.md",
            "language": "markdown",
            "access": "edit",
            "label": None,
        },
    ]
    assert [item.to_dict() for item in inspection.input_scope] == [
        {"path": "view.toml", "kind": "file"},
        {"path": "index.html", "kind": "file"},
        {"path": "styles/app.css", "kind": "file"},
        {"path": "scripts/app.js", "kind": "file"},
    ]
    assert report.document == PurePosixPath("index.html")
    assert (files / "styles" / "app.css").read_bytes() == styles.read_bytes()
    assert (files / "scripts" / "app.js").read_bytes() == script.read_bytes()
    built = (files / "index.html").read_text(encoding="utf-8")
    assert 'href="./styles/app.css?theme=dark"' in built
    assert 'src="./scripts/app.js#boot"' in built
    assert (
        f'data-marimo-studio-source-revision="{hashlib.sha256(script.read_bytes()).hexdigest()}"'
        in built
    )


def test_vanilla_reuses_one_source_for_multiple_script_references(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    entry = project.root / "index.html"
    entry.write_text(
        entry.read_text(encoding="utf-8").replace(
            "</head>",
            """<script src="scripts/app.js?one"></script>
            <script src="./scripts/app.js#two"></script>
            </head>""",
        ),
        encoding="utf-8",
    )
    script = project.root / "scripts" / "app.js"
    script.parent.mkdir()
    script.write_text('document.body.dataset.ready = "true";\n', encoding="utf-8")

    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "shared-script" / "files"
    files.mkdir(parents=True)
    report = provider.build(provider_build_request(project, inspection, files))

    assert inspection.diagnostics == ()
    assert [item.path for item in inspection.editor_documents].count(
        PurePosixPath("scripts/app.js")
    ) == 1
    assert [item.path for item in inspection.input_scope].count(
        PurePosixPath("scripts/app.js")
    ) == 1
    assert report.document == PurePosixPath("index.html")
    assert (files / "scripts" / "app.js").read_bytes() == script.read_bytes()
    built = (files / "index.html").read_text(encoding="utf-8")
    first = 'src="scripts/app.js?one"'
    second = 'src="./scripts/app.js#two"'
    assert built.index(first) < built.index(second)
    revision = hashlib.sha256(script.read_bytes()).hexdigest()
    assert built.count(f'data-marimo-studio-source-revision="{revision}"') == 2


def test_vanilla_resolves_sources_relative_to_a_nested_entrypoint(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    root_entry = project.root / "index.html"
    nested_entry = project.root / "pages" / "index.html"
    nested_entry.parent.mkdir()
    nested_entry.write_text(
        root_entry.read_text(encoding="utf-8")
        .replace("<style>", '<link rel="stylesheet" href="../styles/app.css">\n<style>')
        .replace(
            "</head>",
            '<script type="module" src="./scripts/app.mjs"></script>\n</head>',
        ),
        encoding="utf-8",
    )
    (project.root / "styles").mkdir()
    (project.root / "styles" / "app.css").write_text(
        "body { color: canvastext; }\n",
        encoding="utf-8",
    )
    (project.root / "pages" / "scripts").mkdir()
    (project.root / "pages" / "scripts" / "app.mjs").write_text(
        "export {};\n",
        encoding="utf-8",
    )
    project = replace(project, options={"entrypoint": "pages/index.html"})

    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "nested" / "files"
    files.mkdir(parents=True)
    report = provider.build(provider_build_request(project, inspection, files))

    assert inspection.diagnostics == ()
    assert [item.path.as_posix() for item in inspection.editor_documents] == [
        "pages/index.html",
        "styles/app.css",
        "pages/scripts/app.mjs",
        "AGENTS.md",
    ]
    assert report.document == PurePosixPath("pages/index.html")
    assert (files / "styles" / "app.css").is_file()
    assert (files / "pages" / "scripts" / "app.mjs").is_file()


def test_vanilla_reports_a_missing_local_source(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            '<script src="scripts/app.js"></script></head>',
        ),
        encoding="utf-8",
    )

    missing = provider.inspect(inspection_request(project))

    assert [item.code for item in missing.diagnostics] == ["local-resource-invalid"]
    assert missing.diagnostics[0].source is not None


def test_vanilla_rejects_a_symlinked_local_source(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            '<script src="scripts/app.js"></script></head>',
        ),
        encoding="utf-8",
    )
    outside = tmp_path / "outside.js"
    outside.write_text("export {};\n", encoding="utf-8")
    scripts = project.root / "scripts"
    scripts.mkdir()
    (scripts / "app.js").symlink_to(outside)

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-resource-invalid"]
    assert inspection.diagnostics[0].source is not None


@pytest.mark.parametrize(
    "url",
    (
        "../../outside.js",
        "/scripts/app.js",
        "scripts/CON.js",
    ),
)
def test_vanilla_rejects_nonportable_local_source_paths(
    tmp_path: Path,
    url: str,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            f'<script src="{url}"></script></head>',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-resource-invalid"]
    assert inspection.diagnostics[0].source is not None


def test_vanilla_exposes_instructions_outside_the_build_inputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project.root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (project.root / "DESIGN.md").write_text("# Page design\n", encoding="utf-8")

    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "single" / "files"
    files.mkdir(parents=True)
    report = provider.build(provider_build_request(project, inspection, files))

    assert [item.path.as_posix() for item in inspection.editor_documents] == [
        "index.html",
        "AGENTS.md",
        "DESIGN.md",
    ]
    assert [item.to_dict() for item in inspection.input_scope] == [
        {"path": "view.toml", "kind": "file"},
        {"path": "index.html", "kind": "file"},
    ]
    assert report.document == PurePosixPath("index.html")
    assert [
        path.relative_to(files).as_posix()
        for path in files.rglob("*")
        if path.is_file()
    ] == ["index.html"]


def test_vanilla_build_observes_cancellation_before_copying(tmp_path: Path) -> None:
    project = _project(tmp_path)
    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "cancelled" / "files"
    files.mkdir(parents=True)
    request = provider_build_request(project, inspection, files)
    request.cancellation.cancel()

    result = provider.build(request)

    assert result.document is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["build-cancelled"]
    assert tuple(files.iterdir()) == ()


def test_vanilla_build_requires_every_declared_input(tmp_path: Path) -> None:
    project = _project(tmp_path)
    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "missing-input" / "files"
    files.mkdir(parents=True)
    request = provider_build_request(project, inspection, files)
    request = replace(
        request,
        inputs=tuple(path for path in request.inputs if path.name != "view.toml"),
    )

    with pytest.raises(ValueError, match=r"build input is unavailable: view\.toml"):
        provider.build(request)
