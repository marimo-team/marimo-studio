"""Compile one Typst document with notebook inputs in a separate process.

Usage: python _compile.py ROOT ENTRY INPUTS OUTPUT
       python _compile.py ROOT ENTRY INPUTS --sizes

INPUTS is a JSON object of Typst ``sys.inputs`` strings.

The script imports only the typst package, so Studio can start it quickly and
stop it at its deadline. It prints one JSON object with the compiler warnings,
or with the first error, and exits with status 1 when compilation fails. With
``--sizes`` it writes no PDF and adds the ``<marimo-size>`` records that
``marimo_output()`` places, which give the size each output is placed at.

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


def main() -> int:
    root, entry, inputs_path, output = sys.argv[1:5]
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
    if output == "--sizes":
        # The compile above reports errors at their source, which a query
        # does not, so the query runs on a document that compiles.
        try:
            sizes = typst.query(
                str(Path(root) / entry),
                "<marimo-size>",
                field="value",
                root=root,
                font_paths=[str(fonts)] if fonts.is_dir() else [],
                ignore_system_fonts=True,
                sys_inputs=inputs,
            )
        except typst.TypstError as error:
            print(json.dumps({"error": _diagnostic(error)}))
            return 1
        report["sizes"] = json.loads(sizes)
    else:
        Path(output).write_bytes(document)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
