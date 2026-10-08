import json
import subprocess
from html.parser import HTMLParser

import pytest

from marimo_studio._delivery.html import runtime_document


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r\r\n", "\u2028\n"])
def test_runtime_injection_preserves_shell_attributes_across_line_endings(
    line_ending: str,
) -> None:
    source = line_ending.join(
        [
            "<!doctype html>",
            "<html>",
            '<head><meta charset="utf-8"><title>Report</title></head>',
            "<body>",
            '<main id="app-shell" class="report"></main>',
            '<a id="following">Next</a>',
            "</body></html>",
        ]
    )
    rendered = runtime_document(
        source,
        root_url="./",
        support_url="support.json",
        assets_url="assets",
        dev=False,
        revision="revision",
        runtime="wasm",
        runtime_explicit=False,
        replay=False,
        renewal_token=None,
        filename="notebook.py",
        marimo_version="0.24.2",
    )
    shells: list[dict[str, str | None]] = []

    class Parser(HTMLParser):
        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            attributes = dict(attrs)
            if attributes.get("id") == "app-shell":
                shells.append(attributes)

    Parser().feed(rendered)
    assert len(shells) == 1
    assert shells[0]["class"] == "report"
    assert "data-marimo-lens-scope" in shells[0]


def _rendered_head_scripts(head: str) -> list[str]:
    rendered = runtime_document(
        f"<!doctype html><html><head>{head}</head>"
        '<body><main id="app-shell"></main></body></html>',
        root_url="./",
        support_url="support.json",
        assets_url="assets",
        dev=False,
        revision="revision",
        runtime="server",
        runtime_explicit=False,
        replay=False,
        renewal_token=None,
        filename="notebook.py",
        marimo_version="0.24.2",
    )
    scripts: list[str] = []

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.inline = False

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            if tag == "script":
                values = dict(attrs)
                self.inline = values.get("src") is None
                if not self.inline:
                    scripts.append(f"src:{values['src']}")

        def handle_data(self, data: str) -> None:
            if self.inline and data.strip():
                scripts.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag == "script":
                self.inline = False

    Parser().feed(rendered)
    return scripts


def test_the_storage_fallback_runs_before_authored_head_scripts() -> None:
    scripts = _rendered_head_scripts('<script src="site_libs/quarto.js"></script>')

    fallback = next(
        index for index, item in enumerate(scripts) if "localStorage" in item
    )
    assert fallback < scripts.index("src:site_libs/quarto.js")
    assert "<" not in scripts[fallback]


@pytest.mark.requires_node
def test_the_storage_fallback_behaves_like_storage_in_strict_code() -> None:
    (fallback,) = (
        item for item in _rendered_head_scripts("") if "localStorage" in item
    )
    program = (
        '"use strict";'
        "const window = {};"
        "Object.defineProperty(window, 'localStorage', {configurable: true,"
        " get() { throw new Error('SecurityError'); }});"
        f"{fallback}"
        "const storage = window.localStorage;"
        "storage.setItem('theme', 'dark');"
        "storage.color = 1;"
        "delete storage.missing;"
        "console.log(JSON.stringify([storage.getItem('theme'), storage.color,"
        " storage.length, Object.keys(storage), 'theme' in storage,"
        " storage.key(1)]));"
    )

    completed = subprocess.run(
        ["node", "-e", program], capture_output=True, check=True, text=True
    )

    assert json.loads(completed.stdout) == [
        "dark",
        "1",
        2,
        ["theme", "color"],
        True,
        "color",
    ]
