"""Compile one Typst document with notebook inputs in a separate process.

Usage: python _compile.py ROOT ENTRY INPUTS OUTPUT [--regions=FILE]
       python _compile.py ROOT ENTRY INPUTS --sizes

INPUTS is a JSON object of Typst ``sys.inputs`` strings.

The script imports only the typst package, so Studio can start it quickly and
stop it at its deadline. It prints one JSON object with the compiler warnings,
or with the first error, and exits with status 1 when compilation fails. With
``--sizes`` it writes no PDF and adds the ``<marimo-size>`` records that
``marimo_output()`` places, which give the size each output is placed at.
With ``--regions=FILE`` it also writes FILE with the ``<marimo-region>``
records that locate each output, cell, and ``marimo_region()`` on its page,
and the width and height of every page in points. A long document holds many
records, so they bypass the report.

The compile clock is fixed at the Unix epoch, so the same template and inputs
produce the same PDF bytes and artifact revision on every build.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import typst

_LOCATION = re.compile(r"┌─ (?P<path>.+?):(?P<line>\d+):(?P<column>\d+)")
_VIEW_BOX = re.compile(rb'viewBox="0 0 (?P<width>[\d.]+) (?P<height>[\d.]+)"')


def _diagnostic(item: object) -> dict[str, object]:
    text = str(getattr(item, "diagnostic", "") or "")
    location = _LOCATION.search(text)
    return {
        "message": str(getattr(item, "message", item)),
        "hints": [str(hint) for hint in getattr(item, "hints", ()) or ()],
        "path": location["path"] if location else None,
        "line": int(location["line"]) if location else None,
        "column": int(location["column"]) if location else None,
    }


def _query(root: str, entry: str, label: str, inputs: dict[str, str]) -> object:
    fonts = Path(root) / "fonts"
    return json.loads(
        typst.query(
            str(Path(root) / entry),
            label,
            field="value",
            root=root,
            font_paths=[str(fonts)] if fonts.is_dir() else [],
            ignore_system_fonts=True,
            sys_inputs=inputs,
        )
    )


def _pages(
    compiler: typst.Compiler, root: str, entry: str, inputs: dict[str, str]
) -> list[list[float]]:
    """Return the width and height of every page in points.

    A page with ``height: auto`` takes its height from its content, so the
    sizes come from the laid-out document's SVG pages.
    """
    pages = compiler.compile(
        input=str(Path(root) / entry), format="svg", sys_inputs=inputs, timestamp=0
    )
    sizes: list[list[float]] = []
    for page in pages if isinstance(pages, list) else [pages]:
        match = _VIEW_BOX.search(page) if isinstance(page, bytes) else None
        sizes.append([float(match["width"]), float(match["height"])] if match else [])
    return sizes


def main() -> int:
    root, entry, inputs_path, output = sys.argv[1:5]
    options = dict(item.split("=", 1) for item in sys.argv[5:] if "=" in item)
    regions = options.get("--regions")
    fonts = Path(root) / "fonts"
    compiler = typst.Compiler(
        root=root,
        font_paths=[str(fonts)] if fonts.is_dir() else [],
        ignore_system_fonts=True,
    )
    inputs = json.loads(Path(inputs_path).read_text(encoding="utf-8"))
    try:
        document, warnings = compiler.compile_with_warnings(
            input=str(Path(root) / entry),
            format="pdf",
            sys_inputs=inputs,
            timestamp=0,
        )
    except typst.TypstError as error:
        print(json.dumps({"error": _diagnostic(error)}))
        return 1
    if not isinstance(document, bytes):
        print(json.dumps({"error": {"message": "Typst returned no PDF document."}}))
        return 1
    report: dict[str, object] = {"warnings": [_diagnostic(item) for item in warnings]}
    # The compile above reports errors at their source, which a query does
    # not, so each query runs on a document that compiles.
    try:
        if output == "--sizes":
            report["sizes"] = _query(root, entry, "<marimo-size>", inputs)
        else:
            Path(output).write_bytes(document)
            if regions:
                records = _query(root, entry, "<marimo-region>", inputs)
                pages = _pages(compiler, root, entry, inputs) if records else []
                Path(regions).write_text(
                    json.dumps({"records": records, "pages": pages}),
                    encoding="utf-8",
                )
    except typst.TypstError as error:
        print(json.dumps({"error": _diagnostic(error)}))
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
