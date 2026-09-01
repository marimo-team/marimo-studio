from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers._bundled.vanilla import provider

from ..provider_test_support import provider_build_request
from ._vanilla_test_support import _project, _project_with_local_sources


@pytest.mark.parametrize(
    "markup",
    (
        '<script type="module"/>import "./dependency.js";</script>',
        '<style/>.hero { background: url("./hero.png") }</style>',
    ),
)
def test_vanilla_rejects_self_closing_script_and_style_elements(
    tmp_path: Path,
    markup: str,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace("</head>", f"{markup}</head>"),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "cannot use self-closing syntax" in inspection.diagnostics[0].message


def test_vanilla_rejects_import_maps(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            """<script type="importmap">
              {"imports":{"#mapped":"./dependency.js"}}
            </script></head>""",
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    diagnostic = inspection.diagnostics[0]
    assert (
        "import maps cannot preserve the direct-source allowlist" in diagnostic.message
    )
    assert "explicit remote module URLs" in diagnostic.hint


def test_vanilla_rejects_an_authored_document_base(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            '<base href="./assets/"><script src="./scripts/app.js"></script></head>',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    diagnostic = inspection.diagnostics[0]
    assert "cannot set <base href>" in diagnostic.message
    assert "relative to the HTML entry document" in diagnostic.hint
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("index.html")


def test_vanilla_rejects_inline_local_javascript_dependencies(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            """<script type="module">
              import "./dependency.js";
            </script></head>""",
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    diagnostic = inspection.diagnostics[0]
    assert "local JavaScript import './dependency.js'" in diagnostic.message
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("index.html")
    assert diagnostic.source.line > 1


def test_vanilla_accepts_remote_inline_scripts_and_nonexecutable_data(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            """<script type="application/json">
              {"example":"import './not-a-dependency.js'"}
            </script>
            <script type="module">
              import "https://cdn.example.test/dependency.js";
            </script></head>""",
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert inspection.diagnostics == ()


@pytest.mark.parametrize(
    "resource",
    (
        '<link rel="modulepreload" href="scripts/app.js" />',
        '<link rel="preload" as="style" href="app.css" />',
        '<img src="images/chart.png" alt="Chart" />',
        "<style>.chart { background: url(images/chart.png) }</style>",
        '<div style="background: url(images/chart.png)"></div>',
        '<img srcset="images/small.png 1x, images/large.png 2x" />',
        '<source srcset="https://cdn.example.test/small.png 1x, '
        'images/large.png 2x" />',
        '<link rel="preload" as="image" imagesrcset="images/small.png 1x" />',
        '<svg><image href="images/chart.png" /></svg>',
        '<svg><feImage xlink:href="images/chart.png" /></svg>',
    ),
)
def test_vanilla_rejects_fetched_local_resources(
    tmp_path: Path,
    resource: str,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace("</head>", f"{resource}</head>"),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-resource-invalid"]
    assert "project-local resources must be CSS" in inspection.diagnostics[0].message
    assert inspection.diagnostics[0].source is not None


@pytest.mark.parametrize(
    "dependency",
    (
        '@import "./theme.css";',
        '.hero { background: url("../images/hero.png") }',
    ),
)
def test_vanilla_rejects_transitive_local_css_dependencies(
    tmp_path: Path,
    dependency: str,
) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css=f":root {{ color-scheme: light; }}\n{dependency}\n",
        javascript='document.documentElement.dataset.ready = "true";\n',
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    diagnostic = inspection.diagnostics[0]
    assert "local CSS dependency" in diagnostic.message
    assert "artifact allowlist" in diagnostic.message
    assert "Bundle or inline this dependency" in diagnostic.hint
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("styles/app.css")
    assert diagnostic.source.line == 2
    assert PurePosixPath("styles/app.css") in {
        item.path for item in inspection.editor_documents
    }


@pytest.mark.parametrize(
    ("dependency", "message"),
    (
        ('import "./dependency.js";', "local JavaScript import"),
        ('import value from "../dependency.js";', "local JavaScript import"),
        (r'import "\x2e/dependency.js";', "local JavaScript import"),
        ('export * from "./dependency.js";', "local JavaScript re-export"),
        ('export { value } from "./dependency.js";', "local JavaScript re-export"),
        ('void import("./dependency.js");', "local JavaScript dynamic import"),
        ("void import(`./dependency.js`);", "local JavaScript dynamic import"),
        ('void import("./" + dependency);', "computed dynamic import"),
        (
            'const view = `value ${import("./dependency.js")}`;',
            "local JavaScript dynamic import",
        ),
        (
            'let count = 1; count++ / import("./dependency.js") / scale;',
            "local JavaScript dynamic import",
        ),
        (
            'widget.if() / import("./dependency.js") / scale;',
            "local JavaScript dynamic import",
        ),
        (
            'const ratio = function() {} / import("./dependency.js");',
            "local JavaScript dynamic import",
        ),
        ('// comment\rimport("./dependency.js");', "local JavaScript dynamic import"),
        (
            '// comment\u2028import("./dependency.js");',
            "local JavaScript dynamic import",
        ),
        ('import.source("./dependency.wasm");', "source-phase imports"),
        ('let value = 1; value --> import("./dependency.js");', "dynamic import"),
        (
            'label: { const path = "./dependency.js"; import(path)\n{} }',
            "computed dynamic import",
        ),
        (
            "switch (value) { case 1: { "
            'const path = "./dependency.js"; import(path)\n{} } }',
            "computed dynamic import",
        ),
        (
            'try {} catch { const path = "./dependency.js"; import(path)\n{} }',
            "computed dynamic import",
        ),
        (
            "export default class View { "
            'load() { return import("./dependency.js"); } }',
            "local JavaScript dynamic import",
        ),
    ),
)
def test_vanilla_rejects_transitive_local_javascript_dependencies(
    tmp_path: Path,
    dependency: str,
    message: str,
) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="body { color: canvastext; }\n",
        javascript=f'const label = "ready";\n{dependency}\n',
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    diagnostic = inspection.diagnostics[0]
    assert message in diagnostic.message
    assert "artifact allowlist" in diagnostic.message
    assert "Bundle or inline this dependency" in diagnostic.hint
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("scripts/app.js")
    assert diagnostic.source.line >= 2
    assert PurePosixPath("scripts/app.js") in {
        item.path for item in inspection.editor_documents
    }


def test_vanilla_bounds_module_specifiers_and_diagnostics(tmp_path: Path) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="body { color: canvastext; }\n",
        javascript=f'import "{"a" * 5_000}";\n',
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    diagnostic = inspection.diagnostics[0]
    assert "module specifier exceeds the 4096-character inspection limit" in (
        diagnostic.message
    )
    assert len(diagnostic.message.encode("utf-8")) < 1_024


def test_vanilla_rejects_unparsed_javascript(tmp_path: Path) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="body { color: canvastext; }\n",
        javascript="const broken = ;\n",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    diagnostic = inspection.diagnostics[0]
    assert "syntax the dependency check cannot parse" in diagnostic.message
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("scripts/app.js")


@pytest.mark.parametrize(
    "javascript",
    (
        'export { default } from "https://cdn.example/data.json" '
        'with { type: "json" };',
        'export * from "https://cdn.example/data.json" with { type: "json" };',
    ),
)
def test_vanilla_fails_closed_on_reexport_import_attributes(
    tmp_path: Path,
    javascript: str,
) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="body { color: canvastext; }\n",
        javascript=f"{javascript}\n",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    assert "syntax the dependency check cannot parse" in (
        inspection.diagnostics[0].message
    )


@pytest.mark.parametrize("terminator", ("\r", "\u2028", "\u2029"))
def test_vanilla_locates_dependencies_after_javascript_line_terminators(
    tmp_path: Path,
    terminator: str,
) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="body { color: canvastext; }\n",
        javascript=f'// comment{terminator}import("./dependency.js");\n',
    )

    inspection = provider.inspect(inspection_request(project))

    diagnostic = inspection.diagnostics[0]
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("scripts/app.js")
    assert (diagnostic.source.line, diagnostic.source.column) == (2, 8)


def test_vanilla_accepts_nonlocal_source_dependencies(tmp_path: Path) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="""@import "https://cdn.example.test/theme.css";
.data { background: url(data:image/svg+xml;base64,PHN2Zy8+) }
.fragment { background: url(#gradient) }
""",
        javascript="""#!/usr/bin/env node
import "https://cdn.example.test/app.js";
import data from "https://cdn.example.test/data.json" with { type: "json" };
export { data as default };
export { marker } from "data:text/javascript,export const marker = true";
void import("#mapped-module");
void import("https://cdn.example.test/lazy.json", { with: { type: "json" } });
const metadata = import.meta.url;
class Loader { import(path) { return path; } }
const loader = { import(path) { return path; } };
const multilineLoader = { import(path)
{ return path; } };
// import "./not-a-dependency.js";
/* export * from "./not-a-dependency.js"; */
const fakeString = "import './not-a-dependency.js'";
const fakePattern = /import\\("\\.\\/not-a-dependency\\.js"\\)/;
if (fakeString) /import\\("\\.\\/not-a-dependency\\.js"\\)/.test(fakeString);
if (fakeString) {} /import\\("\\.\\/not-a-dependency\\.js"\\)/.test(fakeString);
for await (const item of []) /import\\("\\.\\/not-a-dependency\\.js"\\)/.test(item);
const matches = [.../import\\("\\.\\/not-a-dependency\\.js"\\)/.exec(fakeString)];
class Empty {} /import\\("\\.\\/not-a-dependency\\.js"\\)/.test(fakeString);
export {}
from
"./not-a-dependency.js";
export default 1
from
"./not-a-dependency.js";
class Fields { import = 1
from
"./not-a-dependency.js" }
const fakeTemplate = `literal ${"import('./not-a-dependency.js')"}`;
const length = fakeString.length + fakePattern.source.length + fakeTemplate.length;
document.documentElement.dataset.ready = String(length);
""",
    )
    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "remote-sources" / "files"
    files.mkdir(parents=True)

    report = provider.build(provider_build_request(project, inspection, files))

    assert inspection.diagnostics == ()
    assert report.diagnostics == ()
    assert (files / "styles" / "app.css").is_file()
    assert (files / "scripts" / "app.js").is_file()


@pytest.mark.parametrize(
    "javascript",
    (
        'if (ready) {} /import(".\\/fake.js")/.test(text);',
        "const loader = { import(value)\n{ return value; } };",
        'export {}\nfrom\n"./fake.js";',
        'export default 1\nfrom\n"./fake.js";',
        'class X {} /import(".\\/fake.js")/.test(text);',
        'for await (const value of []) /import(".\\/fake.js")/.test(value);',
        'const values = [.../import(".\\/fake.js")/.exec(text)];',
        'class Fields { import = 1\nfrom\n"./fake.js" }',
        'debugger\n/import(".\\/fake.js")/.test(text);',
        'var value\n/import(".\\/fake.js")/.test(text);',
        'import "https://cdn.example/x.js"\n/import(".\\/fake.js")/.test(text);',
        r'void import("\150ttps://cdn.example/dependency.js");',
    ),
)
def test_vanilla_accepts_javascript_without_module_dependencies(
    tmp_path: Path,
    javascript: str,
) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css="body { color: canvastext; }\n",
        javascript=f"{javascript}\n",
    )

    inspection = provider.inspect(inspection_request(project))

    assert inspection.diagnostics == ()


def test_vanilla_allows_document_navigation_and_remote_resources(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace(
            "</head>",
            """<script src="https://cdn.example.test/app.js"></script>
            <style>
              @import "https://cdn.example.test/app.css";
              .data { background: url(data:image/svg+xml;base64,PHN2Zy8+) }
              .fragment { background: url(#gradient) }
              .responsive { background: image-set(
                "https://cdn.example.test/chart.png" 1x,
                "data:image/png;base64,iVBORw0KGgo=" 2x
              ) }
              .literal::after { content: "url(images/not-a-resource.png)" }
              /* url(images/not-a-resource.png) */
            </style>
            <img srcset="https://cdn.example.test/small.png 1x,
              data:image/png;base64,iVBORw0KGgo= 2x" />
            </head>""",
        )
        .replace(
            "</main>",
            '<a href="details.html">Details</a></main>',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert inspection.diagnostics == ()


def test_vanilla_reports_malformed_resource_urls_as_project_diagnostics(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            '<style>body { background: url("http://[") }</style></head>',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "Invalid resource URL" in inspection.diagnostics[0].message


@pytest.mark.parametrize(
    "url",
    (
        "https:app.js",
        "https:/app.js",
        "http:app.js",
        "http:/app.js",
    ),
)
def test_vanilla_requires_http_resource_urls_to_name_a_host(
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

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "must include // and a host" in inspection.diagnostics[0].message


@pytest.mark.parametrize(
    ("css", "javascript"),
    (
        ('@import "https:theme.css";\n', "export {};\n"),
        (
            "body { color: canvastext; }\n",
            'import "http:/dependency.js";\n',
        ),
    ),
)
def test_vanilla_rejects_browser_relative_http_source_dependencies(
    tmp_path: Path,
    css: str,
    javascript: str,
) -> None:
    project = _project_with_local_sources(
        tmp_path,
        css=css,
        javascript=javascript,
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["local-source-dependency"]
    assert "must include // and a host" in inspection.diagnostics[0].message
