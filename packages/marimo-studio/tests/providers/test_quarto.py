from __future__ import annotations

import os
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._artifacts.repository import read_profile_state
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._views.inspection import (
    inspect_view_project_sync,
    inspection_request,
)
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import JsonValue, ProviderError, ViewProject
from marimo_studio.view_providers._builtin.quarto import provider

from ..provider_test_support import provider_starter_context, publish

INDEX = PurePosixPath("index.qmd")
_VOID = frozenset({"br", "hr", "img", "input", "link", "meta", "source", "wbr"})


class _Page(HTMLParser):
    """Record the ancestors of each projection host in a rendered page."""

    def __init__(self, page: str) -> None:
        super().__init__()
        self.open: list[str] = []
        self.hosts: dict[str, tuple[str, ...]] = {}
        self.feed(page)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        host = attributes.get("name") or attributes.get("value")
        if tag in {"marimo-cell", "marimo-output"} and host:
            self.hosts[host] = tuple(self.open)
        elif attributes.get("mo-value"):
            self.hosts[attributes["mo-value"] or ""] = tuple(self.open)
        if tag not in _VOID:
            self.open.append(attributes.get("id") or tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID and self.open:
            self.open.pop()


DOCUMENT = """---
title: "Résumé <marimo-output value='front'></marimo-output>"
---

Café ☕ <span mo-value="total"></span> 😀

```python
<marimo-cell name="fenced"></marimo-cell>
```

```{=html}
<marimo-output value="raw_block"></marimo-output>
```

Inline `<marimo-cell name="code"></marimo-cell>` and
`<marimo-cell name="raw_inline"></marimo-cell>`{=html}.

Math $<marimo-cell name="math">$ and {{< kbd Ctrl-<marimo-cell> >}}

    <marimo-cell name="indented"></marimo-cell>

Escaped \\<marimo-cell name="escaped"></marimo-cell> text.

- A list item

    <marimo-output value="in_list"></marimo-output>

        <marimo-cell name="list_code"></marimo-cell>

\\`<marimo-cell name="chart"></marimo-cell>\\`
"""


def _project(
    tmp_path: Path,
    index: str | None = None,
    *,
    files: dict[str, str] | None = None,
    options: dict[str, JsonValue] | None = None,
) -> ViewProject:
    plan = provider.create(
        provider.starters()[0],
        provider_starter_context(tmp_path, view_name="report"),
    )
    root = tmp_path / "report"
    for relative, content in plan.files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/quarto", options),
        encoding="utf-8",
    )
    if index is not None:
        (root / INDEX).write_text(index, encoding="utf-8")
    for relative, content in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return load_view_project(root)


def test_hosts_are_found_where_pandoc_keeps_raw_html(tmp_path: Path) -> None:
    project = _project(tmp_path, DOCUMENT)
    source = DOCUMENT.encode("utf-8")

    inspection = provider.inspect(inspection_request(project))

    assert [
        (site.kind, site.targets, site.source.line) for site in inspection.sites
    ] == [
        ("value", ("total",), 5),
        ("output", ("raw_block",), 12),
        ("cell", ("raw_inline",), 16),
        ("output", ("in_list",), 26),
        ("cell", ("chart",), 30),
    ]
    starts = (
        b'<span mo-value="total"',
        b'<marimo-output value="raw_block"',
        b'<marimo-cell name="raw_inline"',
        b'<marimo-output value="in_list"',
        b'<marimo-cell name="chart"',
    )
    for site, start in zip(inspection.sites, starts, strict=True):
        assert source[: site.offset].endswith(start)


SHORTCODES = """---
title: Rooms
---

Occupancy is {{< marimo value="summary.rate" >}} today, and
{{{< marimo value="escaped" >}}} stays literal.

{{< marimo cell="chart" >}}

{{< marimo output='table' >}}

```markdown
{{< marimo cell="in_code" >}}
```

Inline {{< marimo cell="inline" >}} cell.

{{< marimo cell="both" output="both" >}}

{{< marimo cell="forged" data-marimo-studio-site="site-1" >}}

::: {.callout-note}
{{< marimo output="callout" >}}
:::
"""


def test_marimo_shortcodes_are_projection_sites(tmp_path: Path) -> None:
    project = _project(tmp_path, SHORTCODES)
    source = SHORTCODES.encode("utf-8")

    inspection = provider.inspect(inspection_request(project))

    assert [
        (site.kind, site.targets, site.source.line, site.source.column)
        for site in inspection.sites
    ] == [
        ("value", ("summary.rate",), 5, 14),
        ("cell", ("chart",), 8, 1),
        ("output", ("table",), 10, 1),
        ("output", ("callout",), 23, 1),
    ]
    # Studio inserts the site attribute as one more shortcode parameter.
    for site in inspection.sites:
        assert source[site.offset : site.offset + 4] == b" >}}"
    assert [
        (item.code, item.source and item.source.line) for item in inspection.diagnostics
    ] == [
        ("projection-host-inline", 16),
        ("projection-kind-conflict", 18),
        ("projection-site-reserved", 20),
    ]


def test_output_shortcodes_accept_media_types(tmp_path: Path) -> None:
    document = (
        '{{< marimo output="chart" accept="image/svg+xml, image/png" >}}\n\n'
        '{{< marimo output="table" accept="png" >}}\n\n'
        '{{< marimo output="report" accept="application/pdf" >}}\n'
    )
    project = _project(tmp_path, document)

    inspection = provider.inspect(inspection_request(project))

    (site,) = inspection.sites
    assert (site.targets, site.accept) == (("chart",), ("image/svg+xml", "image/png"))
    assert [
        (diagnostic.code, diagnostic.source and diagnostic.source.line)
        for diagnostic in inspection.diagnostics
    ] == [("projection-accept-invalid", 3), ("projection-accept-invalid", 5)]


def test_markdown_entries_and_their_includes_hold_the_hosts(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        files={
            "_quarto.yml": "project:\n  type: default\n",
            "pages/report.md": (
                "# Report\n\n"
                '{{< marimo cell="summary" >}}\n\n'
                "{{< include _intro.markdown >}}\n\n"
                "{{< include /shared/_footer.qmd >}}\n\n"
                "{{< include _missing.md >}}\n"
            ),
            "pages/_intro.markdown": (
                'Rooms in use: <span mo-value="summary.rooms"></span>.\n\n'
                # Quarto resolves nested includes from the entry's directory.
                "{{< include _detail.md >}}\n"
            ),
            "pages/_detail.md": '{{< marimo output="chart" >}}\n',
            "shared/_footer.qmd": '{{< marimo value="summary.updated" >}}\n',
            "unused.qmd": '{{< marimo cell="unused" >}}\n',
        },
        options={"entrypoint": "pages/report.md"},
    )

    inspection = provider.inspect(inspection_request(project))

    assert [
        (site.source.path.as_posix(), site.targets) for site in inspection.sites
    ] == [
        ("pages/report.md", ("summary",)),
        ("pages/_intro.markdown", ("summary.rooms",)),
        ("shared/_footer.qmd", ("summary.updated",)),
        ("pages/_detail.md", ("chart",)),
    ]
    assert [
        (item.code, item.source and (item.source.path.as_posix(), item.source.line))
        for item in inspection.diagnostics
    ] == [("build-input-missing", ("pages/report.md", 9))]
    assert {document.path.as_posix() for document in inspection.documents} >= {
        "pages/report.md",
        "pages/_intro.markdown",
        "pages/_detail.md",
    }


def test_the_entry_must_be_a_quarto_markdown_document(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        files={"notebook.ipynb": "{}"},
        options={"entrypoint": "notebook.ipynb"},
    )

    with pytest.raises(ProviderError) as raised:
        provider.inspect(inspection_request(project))

    assert raised.value.diagnostic.code == "provider-options-invalid"
    assert "notebook.ipynb" in raised.value.diagnostic.message


def test_every_project_file_except_guidance_is_a_build_input(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    (project.root / "figures").mkdir()
    (project.root / "figures" / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (project.root / "index_files").mkdir()
    (project.root / "index_files" / "stale.js").write_text("", encoding="utf-8")
    (project.root / "raw_files").mkdir()
    (project.root / "raw_files" / "rows.csv").write_text("a\n1\n", encoding="utf-8")

    inspection = inspect_view_project_sync(project)

    assert {item.path.as_posix() for item in inspection.inputs} == {
        "view.toml",
        "index.qmd",
        "figures/logo.svg",
        "raw_files/rows.csv",
    }


def test_a_nested_entry_keeps_its_generated_figures_out_of_the_build(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        options={"entrypoint": "pages/report.qmd"},
        files={
            "pages/report.qmd": "# Report\n",
            "pages/report_files/figure.png": "png",
        },
    )

    inspection = inspect_view_project_sync(project)

    assert "pages/report_files/figure.png" not in {
        item.path.as_posix() for item in inspection.inputs
    }
    assert "pages/report.qmd" in {item.path.as_posix() for item in inspection.inputs}


@pytest.mark.pixi
@pytest.mark.skipif(
    not provider.availability().available,
    reason="Quarto is unavailable",
)
def test_quarto_starter_renders_live_hosts_inside_the_app_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Another Quarto installation's cache entries fail to deserialize, so the
    # build must render with a cache of its own.
    home = tmp_path / "home"
    for cache in (
        home / "Library" / "Caches" / "quarto" / "sass",
        home / ".cache" / "quarto" / "sass",
        home / "AppData" / "Local" / "quarto" / "sass",
    ):
        cache.mkdir(parents=True)
        cache.joinpath("sass.kv").write_bytes(b"written by another Quarto")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    project = _project(
        tmp_path,
        "---\ntitle: Rooms\n---\n\n"
        'Occupancy is <span mo-value="total"></span> today.\n\n'
        '<marimo-cell name="chart"></marimo-cell>\n'
        '<MARIMO-OUTPUT value="table"></MARIMO-OUTPUT>\n',
    )

    published = publish(project)

    hosts = _Page(published.files[PurePosixPath("index.html")].decode()).hosts
    assert set(hosts) == {"total", "chart", "table"}
    assert all("app-shell" in ancestors for ancestors in hosts.values())
    assert "p" not in hosts["chart"] and "p" not in hosts["table"]
    assert hosts["total"][-1] == "p"
    assert [(site.kind, site.targets) for site in published.sites] == [
        ("value", ("total",)),
        ("cell", ("chart",)),
        ("output", ("table",)),
    ]


@pytest.mark.pixi
@pytest.mark.skipif(
    not provider.availability().available,
    reason="Quarto is unavailable",
)
def test_markdown_shortcodes_and_includes_render_bound_hosts(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        files={
            "report.md": (
                "---\ntitle: Rooms\n---\n\n"
                'Occupancy is {{< marimo value="total" >}} today.\n\n'
                '{{< marimo cell="chart" >}}\n\n'
                "{{< include _table.md >}}\n"
            ),
            "_table.md": '{{< marimo output="table" >}}\n',
        },
        options={"entrypoint": "report.md"},
    )

    published = publish(project)

    page = published.files[PurePosixPath("report.html")].decode()
    hosts = _Page(page).hosts
    assert set(hosts) == {"total", "chart", "table"}
    assert all("app-shell" in ancestors for ancestors in hosts.values())
    assert "p" not in hosts["chart"] and "p" not in hosts["table"]
    assert hosts["total"][-1] == "p"
    assert [(site.kind, site.targets) for site in published.sites] == [
        ("value", ("total",)),
        ("cell", ("chart",)),
        ("output", ("table",)),
    ]
    assert all(
        f'data-marimo-studio-site="{site.id}"' in page for site in published.sites
    )
    assert published.diagnostics == ()


@pytest.mark.pixi
@pytest.mark.skipif(
    not provider.availability().available,
    reason="Quarto is unavailable",
)
def test_authored_reader_extensions_apply_beside_raw_hosts(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        "---\ntitle: Rooms\nfrom: markdown+emoji\n---\n\n"
        'Occupancy is <span mo-value="total"></span> today :smile:\n\n'
        '<div mo-value="summary"></div>\n',
    )

    published = publish(project)

    page = published.files[PurePosixPath("index.html")].decode()
    assert "\N{SMILING FACE WITH OPEN MOUTH AND SMILING EYES}" in page
    assert set(_Page(page).hosts) == {"total", "summary"}
    assert all(
        f'data-marimo-studio-site="{site.id}"' in page for site in published.sites
    )


@pytest.mark.pixi
@pytest.mark.skipif(
    not provider.availability().available,
    reason="Quarto is unavailable",
)
def test_quarto_errors_carry_quarto_output_and_name_the_file_to_fix(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "---\ntitle: [unclosed\n---\n\nRooms\n")

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "quarto-render-failed"
    assert diagnostic.message.startswith("YAMLException")
    assert "title: [unclosed" in diagnostic.message
    assert diagnostic.hint == "Fix index.qmd, then save it to render again."


@pytest.mark.parametrize("activated", (False, True))
def test_quarto_from_a_conda_environment_requires_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    activated: bool,
) -> None:
    prefix = tmp_path / "env"
    (prefix / "conda-meta").mkdir(parents=True)
    (prefix / "conda-meta" / "quarto-1.9.38-h0_0.json").write_text("{}")
    if os.name == "nt":
        bin_dir = prefix / "Library" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "quarto.cmd").write_text("@echo 1.9.38\r\n", encoding="utf-8")
    else:
        bin_dir = prefix / "bin"
        bin_dir.mkdir()
        quarto = bin_dir / "quarto"
        quarto.write_text("#!/bin/sh\necho 1.9.38\n", encoding="utf-8")
        quarto.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    if activated:
        monkeypatch.setenv("QUARTO_SHARE_PATH", str(prefix / "share" / "quarto"))
    else:
        monkeypatch.delenv("QUARTO_SHARE_PATH", raising=False)

    availability = provider.availability()

    if activated:
        assert (availability.available, availability.version) == (True, "1.9.38")
    else:
        assert not availability.available
        assert "not activated" in (availability.reason or "")
        assert "pixi shell" in (availability.action or "")
