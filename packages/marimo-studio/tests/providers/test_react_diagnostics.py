from __future__ import annotations

from pathlib import Path, PurePosixPath

from marimo_studio.view_providers._bundled.deno_react.build import _check_diagnostic


def test_react_type_error_identifies_authored_source(tmp_path: Path) -> None:
    work = tmp_path / "view café with spaces" / ".artifacts" / "build" / "work"
    work.mkdir(parents=True)
    output = (
        "Check src/main.tsx\n"
        "TS2451 [ERROR]: Cannot redeclare block-scoped variable 'VIEW_HEADING'.\n"
        'const VIEW_HEADING = "React";\n'
        "      ~~~~~~~~~~~~\n"
        f"    at {work.as_uri()}/src/Chart%20caf%C3%A9.tsx:4:7\n\n"
        "Found 1 error.\n\n"
        "error: Type checking failed."
    )

    diagnostic = _check_diagnostic(
        output,
        work,
        (PurePosixPath("src/Chart café.tsx"), PurePosixPath("src/main.tsx")),
    )

    assert diagnostic.code == "react-check-failed"
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("src/Chart café.tsx")
    assert (diagnostic.source.line, diagnostic.source.column) == (4, 7)
    assert diagnostic.message == (
        "React provider could not type-check source: Check src/main.tsx\n"
        "TS2451 [ERROR]: Cannot redeclare block-scoped variable 'VIEW_HEADING'.\n"
        'const VIEW_HEADING = "React";\n'
        "      ~~~~~~~~~~~~\n"
        "    at src/Chart café.tsx:4:7\n\n"
        "Found 1 error.\n\n"
        "error: Type checking failed."
    )


def test_react_type_error_maps_native_source_paths(tmp_path: Path) -> None:
    work = tmp_path / "view café with spaces" / ".artifacts" / "build" / "work"
    work.mkdir(parents=True)
    relative = Path("src") / "App.tsx"
    output = (
        "TS2322 [ERROR]: Type 'number' is not assignable to type 'string'.\n"
        f"    at {work / relative}:8:2\n"
    )

    diagnostic = _check_diagnostic(output, work, (PurePosixPath("src/App.tsx"),))

    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("src/App.tsx")
    assert (diagnostic.source.line, diagnostic.source.column) == (8, 2)
    assert diagnostic.message.endswith(f"at {relative}:8:2")


def test_react_dependency_error_keeps_external_location_outside_source_catalog(
    tmp_path: Path,
) -> None:
    work = tmp_path / "view café with spaces" / ".artifacts" / "build" / "work"
    work.mkdir(parents=True)
    external = (work.with_name("work-other") / "src" / "App.tsx").as_uri()
    output = (
        "TS2307 [ERROR]: Cannot find module 'missing-package'.\n"
        f"    at {external}:2:1\n"
        f"    at {work.as_uri()}/node_modules/dependency/index.d.ts:3:1\n"
    )

    diagnostic = _check_diagnostic(output, work, (PurePosixPath("src/App.tsx"),))

    assert diagnostic.source is None
    assert diagnostic.message == (
        "React provider could not type-check source: "
        "TS2307 [ERROR]: Cannot find module 'missing-package'.\n"
        f"    at {external}:2:1\n"
        "    at node_modules/dependency/index.d.ts:3:1"
    )
