"""Check the host rules that ``host_site()`` applies to one start tag."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from marimo_studio.view_providers import (
    ProjectDiagnostic,
    ProjectionSite,
    SourceLocation,
    host_site,
    html_sites,
)

TEMPLATE = PurePosixPath("report.tmpl")
SOURCE = SourceLocation(TEMPLATE, 4, 5)


def test_a_template_host_becomes_a_site_at_its_location() -> None:
    site = host_site(
        "marimo-output", {"value": "chart", "accept": "image/png"}, SOURCE, 42
    )

    assert site == ProjectionSite("output", ("chart",), SOURCE, 42, ("image/png",))


def test_a_wildcard_host_accepts_runtime_targets() -> None:
    site = host_site("span", {"mo-value": "rows", "data-marimo-allow": "*"}, SOURCE, 0)

    assert isinstance(site, ProjectionSite)
    assert (site.kind, site.targets) == ("value", "*")


@pytest.mark.parametrize(
    ("tag", "attributes"),
    (
        ("section", {"class": "grid"}),
        ("marimo-output", {"render": "main.typ"}),
    ),
    ids=("ordinary", "render"),
)
def test_elements_without_a_site_return_none(
    tag: str, attributes: dict[str, str | None]
) -> None:
    assert host_site(tag, attributes, SOURCE, 0) is None


@pytest.mark.parametrize(
    ("tag", "attributes", "nested", "code"),
    (
        (
            "main",
            {"data-marimo-studio-site": "site-1"},
            False,
            "projection-site-reserved",
        ),
        (
            "marimo-cell",
            {"name": "a", "mo-value": "b"},
            False,
            "projection-kind-conflict",
        ),
        ("marimo-cell", {"name": "summary"}, True, "projection-host-nested"),
        (
            "marimo-output",
            {"render": "../main.typ"},
            False,
            "projection-render-invalid",
        ),
        (
            "marimo-output",
            {"render": "main.typ", "value": "chart"},
            False,
            "projection-render-invalid",
        ),
        (
            "marimo-output",
            {"render": "main.typ", "mo-value": "chart"},
            False,
            "projection-kind-conflict",
        ),
        ("marimo-cell", {}, False, "projection-target-missing"),
        ("span", {"mo-value": None}, False, "projection-target-missing"),
        ("marimo-cell", {"name": "1st plot"}, False, "projection-target-invalid"),
        ("span", {"mo-value": "a..b"}, False, "projection-target-invalid"),
        (
            "span",
            {"mo-value": "a", "data-marimo-allow": None},
            False,
            "projection-wildcard-invalid",
        ),
        (
            "marimo-output",
            {"value": "chart", "accept": "text/html"},
            False,
            "projection-accept-invalid",
        ),
        (
            "marimo-cell",
            {"name": "summary", "accept": "image/png"},
            False,
            "projection-accept-invalid",
        ),
    ),
    ids=(
        "reserved",
        "two-kinds",
        "nested",
        "render-path",
        "render-value",
        "render-selector",
        "missing-name",
        "valueless-selector",
        "cell-name",
        "selector",
        "wildcard",
        "media-type",
        "cell-accept",
    ),
)
def test_invalid_hosts_report_a_located_diagnostic(
    tag: str, attributes: dict[str, str | None], nested: bool, code: str
) -> None:
    diagnostic = host_site(tag, attributes, SOURCE, 0, nested=nested)

    assert isinstance(diagnostic, ProjectDiagnostic)
    assert (diagnostic.code, diagnostic.severity, diagnostic.source) == (
        code,
        "error",
        SOURCE,
    )


def test_html_sites_reports_every_invalid_host_and_keeps_the_valid_ones() -> None:
    page = (
        b'<span mo-value="a..b"></span>\n'
        b"<marimo-cell></marimo-cell>\n"
        b'<marimo-cell name="summary"></marimo-cell>\n'
    )

    sites, diagnostics = html_sites(PurePosixPath("index.html"), page)

    assert [(site.targets, site.source.line) for site in sites] == [(("summary",), 3)]
    assert [(item.code, item.source and item.source.line) for item in diagnostics] == [
        ("projection-target-invalid", 1),
        ("projection-target-missing", 2),
    ]
