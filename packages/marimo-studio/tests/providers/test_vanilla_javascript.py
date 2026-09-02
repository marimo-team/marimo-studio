from __future__ import annotations

import pytest

from marimo_studio.view_providers._bundled.vanilla._javascript import (
    JavaScriptDependency,
    javascript_dependencies,
)


@pytest.mark.parametrize(
    ("source", "kind", "specifier"),
    (
        ('import "./dependency.js";', "import", "./dependency.js"),
        (
            'import value from "./dependency.js" with { type: "json" };',
            "import",
            "./dependency.js",
        ),
        ('export * from "./dependency.js";', "re-export", "./dependency.js"),
        ('void import("./dependency.js");', "dynamic import", "./dependency.js"),
        ('void import("./" + name);', "dynamic import", None),
        ('import.source("./dependency.wasm");', "source import", None),
    ),
)
def test_javascript_dependencies_reports_module_edges(
    source: str,
    kind: str,
    specifier: str | None,
) -> None:
    dependencies = list(javascript_dependencies(source))

    assert [(item.kind, item.specifier) for item in dependencies] == [(kind, specifier)]


@pytest.mark.parametrize(
    "source",
    (
        'if (ready) {} /import(".\\/fake.js")/.test(text);',
        "const loader = { import(value)\n{ return value; } };",
        'export {}\nfrom\n"./fake.js";',
        'debugger\n/import(".\\/fake.js")/.test(text);',
        'debugger // note\n/import(".\\/fake.js")/.test(text);',
        'debugger /* note */\r\n/import(".\\/fake.js")/.test(text);',
        'if (ready) debugger\n/import(".\\/fake.js")/.test(text);',
        'while (ready) debugger\n/import(".\\/fake.js")/.test(text);',
        'label: debugger\n/import(".\\/fake.js")/.test(text);',
        'var value\n/import(".\\/fake.js")/.test(text);',
        'var value   \r\n/import(".\\/fake.js")/.test(text);',
        'var value\u00a0\n/import(".\\/fake.js")/.test(text);',
        'var value\ufeff\n/import(".\\/fake.js")/.test(text);',
        'var value <!-- note\n/import(".\\/fake.js")/.test(text);',
        'debugger <!-- note\n/import(".\\/fake.js")/.test(text);',
        'const values = [.../import(".\\/fake.js")/.exec(text)];',
        'class Fields { import = 1\nfrom\n"./fake.js" }',
        'switch (value) { case 1: debugger\n/import(".\\/fake.js")/.test(text); }',
        'if (ready) run(); else debugger\n/import(".\\/fake.js")/.test(text);',
    ),
)
def test_javascript_dependencies_ignores_non_module_syntax(source: str) -> None:
    assert list(javascript_dependencies(source)) == []


def test_javascript_dependencies_decodes_classic_octal_escape() -> None:
    dependencies = list(
        javascript_dependencies(r'void import("\150ttps://cdn.example/app.js");')
    )

    assert dependencies == [
        JavaScriptDependency("dynamic import", "https://cdn.example/app.js", 12)
    ]


def test_javascript_dependencies_reports_character_offsets() -> None:
    source = 'const café = true;\nimport "./dependency.js";'

    dependencies = list(javascript_dependencies(source))

    assert dependencies == [
        JavaScriptDependency("import", "./dependency.js", source.index('"'))
    ]


def test_javascript_dependencies_fails_closed_on_parse_error() -> None:
    dependencies = list(javascript_dependencies("const broken = ;"))

    assert [(item.kind, item.specifier) for item in dependencies] == [
        ("parse error", None)
    ]


@pytest.mark.parametrize(
    "source",
    (
        'export { default } from "https://cdn.example/data.json" '
        'with { type: "json" };',
        'export * from "https://cdn.example/data.json" with { type: "json" };',
    ),
)
def test_javascript_dependencies_fails_closed_on_reexport_import_attributes(
    source: str,
) -> None:
    assert {item.kind for item in javascript_dependencies(source)} == {"parse error"}
