from __future__ import annotations

from urllib.parse import urljoin

import pytest

from marimo_studio._delivery.urls import relative_url

PREFIXES = ("", "/s/f3a9/p/77c1", "/user/a%2Fb/proxy/2718")
# A directory, a file, and an encoded slash that stays inside its segment.
BASES = ("/", "/studio/dashboard/", "/studio/dashboard", "/studio%2Fdashboard")
TARGETS = (
    "/",
    "/_marimo-studio/editor/?file=notebook.py&session_id=s_1",
    # A first segment that would read as a URL scheme without `./`.
    "/a:b/",
)


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("base", BASES)
@pytest.mark.parametrize("target", TARGETS)
def test_reference_resolves_to_its_target_beneath_any_prefix(
    prefix: str,
    base: str,
    target: str,
) -> None:
    carrier = f"https://workbench.example{prefix}{base}"

    resolved = urljoin(carrier, relative_url(base, target))

    assert resolved == f"https://workbench.example{prefix}{target}"


@pytest.mark.parametrize("target", (*TARGETS, "//evil.example/"))
def test_reference_stays_relative(target: str) -> None:
    assert relative_url("/studio/dashboard/", target).startswith(("./", "../"))


def test_reference_keeps_an_empty_leading_segment_beneath_the_mount() -> None:
    # Browsers resolve `.//evil.example/` to `<mount>//evil.example/`.
    assert relative_url("/", "//evil.example/") == ".//evil.example/"


@pytest.mark.parametrize(
    ("base", "target"),
    [
        ("studio/", "/"),
        ("/", "studio/"),
        ("/studio/?view=dashboard", "/"),
        ("/studio/#top", "/"),
    ],
)
def test_reference_requires_query_free_app_paths(base: str, target: str) -> None:
    with pytest.raises(ValueError):
        relative_url(base, target)
