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
