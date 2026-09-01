"""Protect CSS resource order and nested function context."""

from marimo_studio.view_providers._css_resources import css_resource_urls
from marimo_studio.view_providers._document import HTMLDocumentParser


def test_css_resources_keep_nested_function_context_and_source_order() -> None:
    source = r""".image {
  background: image-set(
    "first.png" 1x,
    linear-gradient(red, blue) 2x,
    type("image/png"),
    url("second.png") 3x
  );
}
@import "third.css";
.escaped { background: u\72l("fourth.png"); }
/**//**//**//**//**//**//**//**/url("fifth.png");
"""

    resources = css_resource_urls(source)

    assert [value for value, _offset in resources] == [
        "first.png",
        "second.png",
        "third.css",
        "fourth.png",
        "fifth.png",
    ]


def test_html_css_resources_preserve_positions_across_rules() -> None:
    parser = HTMLDocumentParser()

    parser.feed(
        """<style>
.first { background: url("first.png") }
.second { background: url(second.png) }
.third { background: url('third.png') }
</style>"""
    )

    assert [
        (resource.value, resource.position[0]) for resource in parser.local_resources
    ] == [
        ("first.png", 2),
        ("second.png", 3),
        ("third.png", 4),
    ]
