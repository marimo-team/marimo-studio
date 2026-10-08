from __future__ import annotations

import base64
import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import marimo_export.values
import pytest
from marimo_export.values import Representation

from marimo_studio._projections import media_output as media_output_module
from marimo_studio._projections.media_output import media_output
from marimo_studio._projections.runtime_records import output_representation

PDF = Representation("application/pdf", b"%PDF-1.7 figure")
SVG = Representation("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
PNG = Representation("image/png", b"\x89PNG\r\n\x1a\n figure", 300, 200)


def _data_url(representation: Representation) -> str:
    encoded = base64.b64encode(representation.data).decode("ascii")
    return f"data:{representation.media_type};base64,{encoded}"


def test_media_travels_as_a_base64_data_url() -> None:
    assert media_output(SVG) == ("image/svg+xml", _data_url(SVG))
    assert media_output(PDF) == ("application/pdf", _data_url(PDF))


def test_a_sized_image_travels_in_a_marimo_mimebundle_with_its_display_size() -> None:
    mimetype, data = media_output(PNG)

    assert mimetype == "application/vnd.marimo+mimebundle"
    assert json.loads(data) == {
        "image/png": _data_url(PNG),
        "__metadata__": {"image/png": {"width": 300, "height": 200}},
    }


@pytest.mark.parametrize("representation", [PDF, SVG, PNG])
def test_output_data_decodes_to_the_same_representation(
    representation: Representation,
) -> None:
    assert output_representation(*media_output(representation)) == representation


@pytest.mark.parametrize(
    ("mimetype", "data"),
    [
        ("text/html", "<b>native output</b>"),
        ("image/png", "data:image/png;base64,%%"),
        ("image/png", "data:image/svg+xml;base64,PHN2Zy8+"),
        ("image/png", b"\x89PNG"),
        ("application/vnd.marimo+mimebundle", "{"),
        (
            "application/vnd.marimo+mimebundle",
            json.dumps({"image/png": _data_url(PNG), "image/svg+xml": _data_url(SVG)}),
        ),
    ],
)
def test_other_output_data_carries_no_representation(
    mimetype: str, data: object
) -> None:
    assert output_representation(mimetype, data) is None


def test_the_browser_bridge_sources_run_with_only_the_standard_library(
    tmp_path: Path,
) -> None:
    # The Pyodide bridge execs these two module sources, where neither
    # marimo-export nor Studio is installed.
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            [
                inspect.getsource(marimo_export.values),
                inspect.getsource(media_output_module),
            ]
        ),
        encoding="utf-8",
    )
    script = tmp_path / "check.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, sys, types

            names = ("bridge_values", "bridge_media")
            modules = []
            for name, source in zip(names, json.loads(open(sys.argv[1]).read())):
                module = types.ModuleType(name)
                sys.modules[name] = module
                exec(compile(source, name, "exec"), module.__dict__)
                modules.append(module)
            values, media = modules


            class Image:
                def _repr_png_(self):
                    data = b"\\x89PNG\\r\\n\\x1a\\n pixels"
                    return data, {"width": 300, "height": 200}


            representation = values.represent(Image(), ["image/png"])
            print(json.dumps(media.media_output(representation)))
            """
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(script), str(sources)],
        capture_output=True,
        check=True,
        text=True,
    )

    mimetype, data = json.loads(completed.stdout)
    assert output_representation(mimetype, data) == Representation(
        "image/png", b"\x89PNG\r\n\x1a\n pixels", 300, 200
    )
