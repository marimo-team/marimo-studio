from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._delivery.portability import (
    projection_portability,
    verify_projection_portability,
)
from marimo_studio._delivery.preflight import preflight_static_bundle
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio.view_providers import MountDeclaration, SourceLocation


def _preflight(
    root: Path,
):
    with secure_directory(root) as filesystem:
        return preflight_static_bundle(
            filesystem,
            view="dashboard",
            runtime="wasm",
            document=PurePosixPath("index.html"),
            projections=(),
        )


def test_static_preflight_resolves_html_css_module_and_worker_references(
    tmp_path: Path,
) -> None:
    tmp_path.joinpath("index.html").write_text(
        """<!doctype html>
<html><head><link rel="stylesheet" href="./assets/app.css"></head>
<body><script type="module" src="./assets/app.js"></script></body></html>
""",
        encoding="utf-8",
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    assets.joinpath("app.css").write_text(
        'body { background: url("./texture.svg"); }',
        encoding="utf-8",
    )
    assets.joinpath("app.js").write_text(
        'import "./feature.js"; new Worker(new URL("worker.js", import.meta.url));',
        encoding="utf-8",
    )
    assets.joinpath("feature.js").write_text("export {};", encoding="utf-8")
    assets.joinpath("worker.js").write_text("self.close();", encoding="utf-8")
    assets.joinpath("texture.svg").write_text("<svg></svg>", encoding="utf-8")

    report = _preflight(tmp_path)

    assert report.ok
    assert report.issues == ()
    assert report.references == 5
    assert report.inspected_files == 5


def test_static_preflight_reports_local_machine_and_missing_module_paths(
    tmp_path: Path,
) -> None:
    tmp_path.joinpath("index.html").write_text(
        """<!doctype html><html><head></head><body>
<script type="module" src="./app.js"></script></body></html>
""",
        encoding="utf-8",
    )
    tmp_path.joinpath("app.js").write_text(
        """import "missing-package";
import "./missing.js";
void import("file:///Users/example/.cache/deno/pdf.js");
""",
        encoding="utf-8",
    )

    report = _preflight(tmp_path)

    assert not report.ok
    assert [issue.code for issue in report.issues] == [
        "static-bare-module",
        "static-reference-missing",
        "static-file-url",
    ]
    assert report.issues[-1].source.line == 3
    assert report.issues[-1].reference == ("file:///Users/example/.cache/deno/pdf.js")
    assert report.issues[0].severity == "warning"


def test_static_preflight_warns_for_computed_dynamic_imports(tmp_path: Path) -> None:
    tmp_path.joinpath("index.html").write_text(
        "<!doctype html><html><head></head><body></body></html>",
        encoding="utf-8",
    )
    tmp_path.joinpath("app.js").write_text(
        'void import("./features/" + selected);',
        encoding="utf-8",
    )

    report = _preflight(tmp_path)

    assert report.ok
    assert [(issue.code, issue.severity) for issue in report.issues] == [
        ("static-module-computed", "warning")
    ]


def test_static_preflight_warns_for_an_unmaterialized_url_constructor(
    tmp_path: Path,
) -> None:
    tmp_path.joinpath("index.html").write_text(
        "<!doctype html><html><head></head><body></body></html>",
        encoding="utf-8",
    )
    tmp_path.joinpath("app.js").write_text(
        'const profile = new URL("./data/profile.icc", import.meta.url);',
        encoding="utf-8",
    )

    report = _preflight(tmp_path)

    assert report.ok
    assert [(issue.code, issue.severity) for issue in report.issues] == [
        ("static-url-target-missing", "warning")
    ]


def test_static_preflight_rejects_file_urls_in_html_attributes(tmp_path: Path) -> None:
    tmp_path.joinpath("index.html").write_text(
        """<!doctype html><html><head></head><body>
<script src=file:///Users/example/app.js></script></body></html>
""",
        encoding="utf-8",
    )

    report = _preflight(tmp_path)

    assert not report.ok
    assert report.issues[0].code == "static-file-url"
    assert report.issues[0].reference == "file:///Users/example/app.js"


@pytest.mark.parametrize(
    ("specifier", "code"),
    (
        ("/assets/app.js", "static-root-absolute-url"),
        ("../../outside.js", "static-reference-outside-bundle"),
        (r"C:\\Users\\example\\app.js", "static-file-path"),
        ("http://[invalid", "static-reference-invalid"),
    ),
)
def test_static_preflight_rejects_nonrelocatable_module_paths(
    tmp_path: Path,
    specifier: str,
    code: str,
) -> None:
    tmp_path.joinpath("index.html").write_text(
        "<!doctype html><html><head></head><body></body></html>",
        encoding="utf-8",
    )
    tmp_path.joinpath("app.js").write_text(
        f"void import({specifier!r});",
        encoding="utf-8",
    )

    report = _preflight(tmp_path)

    assert not report.ok
    assert report.issues[0].code == code


def test_projection_portability_keeps_runtime_choice_explicit() -> None:
    finite = MountDeclaration(
        "finite",
        "value",
        SourceLocation(PurePosixPath("src/App.tsx"), 4, 5),
        ("metrics",),
    )
    dynamic = MountDeclaration(
        "dynamic",
        "cell",
        SourceLocation(PurePosixPath("src/App.tsx"), 8, 5),
        None,
    )

    zero_python = projection_portability((finite, dynamic), "zero-python")
    wasm = projection_portability((finite, dynamic), "wasm")

    assert [item.status for item in zero_python] == [
        "incompatible",
        "verification-required",
    ]
    assert [item.status for item in wasm] == ["supported", "supported"]
    verified = verify_projection_portability(zero_python)
    assert [item.status for item in verified] == ["incompatible", "verified"]
