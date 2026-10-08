"""Exercise React analysis, containment, build, and determinism."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers._artifact_sites import artifact_sites
from marimo_studio.view_providers._builtin import _deno
from marimo_studio.view_providers._builtin._deno import cache as _deno_cache
from marimo_studio.view_providers._builtin._deno import runtime as _deno_runtime
from marimo_studio.view_providers._builtin.deno_react import build as _react_build
from marimo_studio.view_providers._builtin.deno_react import provider as react_provider
from marimo_studio.view_providers._host import provider_registry

from ..deno_provider_test_support import build_provider as _build
from ..deno_provider_test_support import inspect_provider as _inspect
from ..deno_provider_test_support import project as _project
from ..helpers import no_display_notebook_source
from ..provider_test_support import provider_build_request

pytestmark = [
    pytest.mark.deno,
    pytest.mark.usefixtures("shared_deno_test_cache"),
]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_output_hosts_report_their_literal_accept_list(tmp_path: Path) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    source = root / "src" / "App.tsx"
    source.write_text(
        """const formats = "image/png";
export const App = () => (
  <main>
    <marimo-output value="chart" accept="image/svg+xml, image/png" />
    <marimo-output value="table" accept={formats} />
    <marimo-output value="report" accept="" />
    <marimo-cell name="summary" accept="image/png" />
  </main>
);
""",
        encoding="utf-8",
    )

    inspection = _inspect(react_provider, project)

    (site,) = inspection.sites
    assert (site.targets, site.accept) == (("chart",), ("image/svg+xml", "image/png"))
    assert [
        (diagnostic.code, diagnostic.source and diagnostic.source.line)
        for diagnostic in inspection.diagnostics
    ] == [
        ("projection-accept-dynamic", 5),
        ("projection-accept-invalid", 6),
        ("projection-accept-invalid", 7),
    ]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_inspection_tracks_literal_site_identity_and_kind(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    source = root / "src" / "App.tsx"
    source.write_text(
        """export const App = () => (
  <div aria-label="😀">
    <marimo-cell name="controls"></marimo-cell>
    <marimo-cell name="controls"></marimo-cell>
  </div>
);
""",
        encoding="utf-8",
    )

    inspection = _inspect(react_provider, project)

    assert [site.targets for site in inspection.sites] == [
        ("controls",),
        ("controls",),
    ]
    assert len({site.id for site in artifact_sites(inspection.sites)}) == 2

    source.write_text(
        """export const App = () => (
  <main>
    <div mo-value=" report.total "></div>
    <marimo-cell name=" controls "></marimo-cell>
    <marimo-output value=" summary "></marimo-output>
  </main>
);
""",
        encoding="utf-8",
    )
    padded_sites = _inspect(react_provider, project).sites
    source.write_text(
        """export const App = () => (
  <main>
    <div mo-value="report.total"></div>
    <marimo-cell name="controls"></marimo-cell>
    <marimo-output value="summary"></marimo-output>
  </main>
);
""",
        encoding="utf-8",
    )
    canonical_sites = _inspect(react_provider, project).sites

    assert {site.kind: site.targets for site in padded_sites} == {
        "cell": ("controls",),
        "output": ("summary",),
        "value": ("report.total",),
    }
    assert {site.kind: site.id for site in artifact_sites(padded_sites)} == {
        site.kind: site.id for site in artifact_sites(canonical_sites)
    }

    source.write_text(
        """export const App = () => (
  <marimo-output value="summary" mo-value="summary"></marimo-output>
);
""",
        encoding="utf-8",
    )
    conflict = _inspect(react_provider, project)

    assert [item.code for item in conflict.diagnostics] == ["projection-kind-conflict"]
    assert conflict.sites == ()


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_default_starter_declares_notebook_cell_targets(
    tmp_path: Path,
) -> None:
    _root, project = _project(tmp_path, react_provider, "marimo-studio/react")

    inspection = _inspect(react_provider, project)

    assert [(site.kind, site.targets) for site in inspection.sites] == [
        ("cell", ("cell-2",)),
    ]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_keeps_mutated_static_domains_fail_closed(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    (root / "src" / "App.tsx").write_text(
        """const cells: string[] = [];
cells.push("secret");

export const App = () => (
  <main>
    {cells.map((name) => (
      <marimo-cell key={name} name={name} data-marimo-studio-site="forged" />
    ))}
  </main>
);
""",
        encoding="utf-8",
    )

    inspection = _inspect(react_provider, project)

    assert [item.code for item in inspection.diagnostics] == [
        "projection-site-reserved"
    ]
    assert inspection.sites == ()


@pytest.mark.parametrize("starter_key", ("default", "reveal"))
@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_starters_build_without_possible_output_cells(
    tmp_path: Path,
    starter_key: str,
) -> None:
    tmp_path.joinpath("analysis.py").write_text(
        no_display_notebook_source(),
        encoding="utf-8",
    )
    root, project = _project(
        tmp_path,
        react_provider,
        "marimo-studio/react",
        starter_key=starter_key,
    )
    inspection = _inspect(react_provider, project)
    files = root / ".artifacts" / ".staging" / "zero-display" / "files"
    files.mkdir(parents=True)

    report = _build(
        react_provider,
        provider_build_request(project, inspection, files),
    )

    assert inspection.diagnostics == ()
    assert inspection.sites == ()
    assert report.document is not None


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_projection_diagnostics_locate_authored_sources(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    (root / "src" / "App.tsx").write_text(
        """export const App = () => (
  <main>
    <marimo-cell target="controls"></marimo-cell>
    <marimo-output name="summary"></marimo-output>
    <span mo-value></span>
  </main>
);
""",
        encoding="utf-8",
    )

    diagnostics = _inspect(react_provider, project).diagnostics

    assert [
        (
            item.code,
            item.source.path if item.source is not None else None,
            item.source.line if item.source is not None else None,
        )
        for item in diagnostics
    ] == [
        ("projection-target-missing", PurePosixPath("src/App.tsx"), 3),
        ("projection-target-missing", PurePosixPath("src/App.tsx"), 4),
        ("projection-target-missing", PurePosixPath("src/App.tsx"), 5),
    ]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_source_opens_on_the_app_component(tmp_path: Path) -> None:
    _root, project = _project(tmp_path, react_provider, "marimo-studio/react")

    documents = _inspect(react_provider, project).documents

    assert documents[0].path == PurePosixPath("src/App.tsx")
    assert documents[-1].path == PurePosixPath("deno.lock")


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_starter_types_projections(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    (root / "src" / "App.tsx").write_text(
        """/// <reference path="./marimo-studio.d.ts" />

import {
  getMarimoDataSource,
  type MarimoTable,
  useMarimoValue,
} from "./lib/use-marimo-value.ts";

type Row = { id: string; label: string };

export const App = () => {
  const { error, hostRef, value } = useMarimoValue<MarimoTable<Row>>("rows");
  const sourceBytes = getMarimoDataSource(value)?.bytes.byteLength;
  return (
    <main>
      <span ref={hostRef} hidden mo-value="rows" />
      <output>
        {error ? error.message : value?.get(0)?.label ?? sourceBytes ?? 0}
      </output>
      <marimo-cell name="summary" />
      <marimo-output value="rows" />
    </main>
  );
};
""",
        encoding="utf-8",
    )
    inspection = _inspect(react_provider, project)
    files = root / ".artifacts" / ".staging" / "typed-starter" / "files"
    files.mkdir(parents=True)

    report = _build(
        react_provider,
        provider_build_request(project, inspection, files),
    )

    assert report.document is not None


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_points_an_unadded_package_to_the_dependency_workflow(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    app = root / "src" / "App.tsx"
    app.write_text(
        app.read_text(encoding="utf-8")
        + 'import embed from "vega-embed";\nexport const embedChart = embed;\n',
        encoding="utf-8",
    )
    inspection = _inspect(react_provider, project)
    files = root / ".artifacts" / ".staging" / "missing-package" / "files"
    files.mkdir(parents=True)

    report = _build(
        react_provider,
        provider_build_request(project, inspection, files),
    )

    assert report.document is None
    assert [item.code for item in report.diagnostics] == ["react-check-failed"]
    assert "vega-embed" in report.diagnostics[0].message
    assert "AGENTS.md" in report.diagnostics[0].hint


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_points_a_failed_package_download_to_the_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The inspection gets its own empty cache, since the process-owned one may
    # hold packages from an earlier test, and the proxy refuses connections, so
    # Deno must download packages and fails. Deno routes through ALL_PROXY
    # before HTTPS_PROXY, so an inherited ALL_PROXY must not apply.
    monkeypatch.setattr(
        _deno_runtime, "ensure_cache_directory", _deno_cache.ensure_cache_directory
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    for name in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    _root, project = _project(tmp_path, react_provider, "marimo-studio/react")

    inspection = react_provider.inspect(
        inspection_request(project, cache_root=tmp_path / "inspection-cache")
    )

    assert [item.code for item in inspection.diagnostics] == [
        "provider-analysis-failed"
    ]
    assert "Failed caching npm package" in inspection.diagnostics[0].message
    assert "network connection" in inspection.diagnostics[0].hint


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_reveal_starter_builds_a_deck_from_notebook_cells(
    tmp_path: Path,
) -> None:
    root, project = _project(
        tmp_path,
        react_provider,
        "marimo-studio/react",
        starter_key="reveal",
    )
    inspection = _inspect(react_provider, project)
    files = root / ".artifacts" / ".staging" / "reveal-starter" / "files"
    files.mkdir(parents=True)
    report = _build(
        react_provider,
        provider_build_request(project, inspection, files),
    )

    assert [(site.kind, site.targets) for site in inspection.sites] == [
        ("cell", ("cell-2",)),
    ]
    assert report.document is not None


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_maps_extract_bounded_and_wildcard_mounts(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    (root / "src" / "targets.ts").write_text(
        'export const importedCells = [" imported ", "detail", "detail"] as const;\n',
        encoding="utf-8",
    )
    (root / "src" / "App.tsx").write_text(
        """import { importedCells } from "./targets.ts";

declare const runtimeCells: readonly string[];
const localCells = [{ name: "overview" }, { name: "detail" }] as const;
const values = { total: " report.total ", change: "report.change" } as const;
const outputs = { summary: "summary", table: "detail_table" } as const;

export const App = () => (
  <main>
    {localCells.map((item) => <marimo-cell name={item.name}></marimo-cell>)}
    {importedCells.map((name) => <marimo-cell name={name}></marimo-cell>)}
    {runtimeCells.map((name) => (
      <marimo-cell name={name} data-marimo-allow="*"></marimo-cell>
    ))}
    {Object.values(values).map((value) => <strong mo-value={value}></strong>)}
    {Object.values(outputs).map((output) => (
      <marimo-output value={output}></marimo-output>
    ))}
  </main>
);
""",
        encoding="utf-8",
    )

    inspection = _inspect(react_provider, project)

    assert [site.kind for site in inspection.sites] == [
        "cell",
        "cell",
        "cell",
        "value",
        "output",
    ]
    assert [site.targets for site in inspection.sites] == [
        ("overview", "detail"),
        ("imported", "detail"),
        "*",
        ("report.total", "report.change"),
        ("summary", "detail_table"),
    ]

    source = root / "src" / "App.tsx"
    source.write_text(
        source.read_text(encoding="utf-8").replace(' data-marimo-allow="*"', ""),
        encoding="utf-8",
    )
    diagnostic = next(
        item
        for item in _inspect(react_provider, project).diagnostics
        if item.code == "projection-target-unbounded"
    )
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("src/App.tsx")


def test_react_inspection_rejects_undeclared_entrypoint_option(
    tmp_path: Path,
) -> None:
    _root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    project = replace(
        project,
        options={**project.options, "entrypoint": "src/index.html"},
    )

    inspection = _inspect(provider_registry().get(project.provider), project)

    diagnostic = next(
        item
        for item in inspection.diagnostics
        if item.code == "provider-options-invalid"
    )
    assert (
        diagnostic.message == "view.toml sets 'entrypoint', which React does not read."
    )
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("view.toml")
    assert "view.toml" in diagnostic.hint
    assert all(
        document.path.as_posix() != "view.toml" for document in inspection.documents
    )


def test_react_inspection_requires_fixed_entry_document(tmp_path: Path) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    (root / "src" / "index.html").unlink()

    inspection = _inspect(provider_registry().get(project.provider), project)

    assert [
        item.message
        for item in inspection.diagnostics
        if item.code == "build-input-missing"
    ] == ["marimo-studio/react requires src/index.html."]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_inspection_rejects_module_targets_outside_snapshot(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    sentinel = tmp_path / "outside.ts"
    sentinel.write_text("export default 'outside';\n", encoding="utf-8")
    for target in ("../../../outside.ts", "/tmp/outside.ts", "file:///tmp/outside.ts"):
        (root / "src" / "App.tsx").write_text(
            f"import outside from {json.dumps(target)};\n"
            "export const App = () => <main>{outside}</main>;\n",
            encoding="utf-8",
        )

        inspection = _inspect(react_provider, project)

        assert "module-path-outside-project" in {
            diagnostic.code for diagnostic in inspection.diagnostics
        }, target
        assert sentinel.read_text(encoding="utf-8") == "export default 'outside';\n"


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_inspection_rejects_html_module_outside_snapshot(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    entry = root / "src" / "index.html"
    entry.write_text(
        entry.read_text(encoding="utf-8").replace(
            'src="./main.tsx"',
            'src="../../outside.tsx"',
        ),
        encoding="utf-8",
    )

    inspection = _inspect(react_provider, project)

    assert "module-path-outside-project" in {
        diagnostic.code for diagnostic in inspection.diagnostics
    }


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_inspection_rejects_configured_project_escape(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    config_path = root / "deno.json"
    original = json.loads(config_path.read_text(encoding="utf-8"))
    for field in ("imports", "workspace", "links"):
        config = dict(original)
        config[field] = (
            {"outside": "../outside.ts"} if field == "imports" else ["../outside"]
        )
        config_path.write_text(json.dumps(config), encoding="utf-8")

        inspection = _inspect(react_provider, project)

        assert {diagnostic.code for diagnostic in inspection.diagnostics} & {
            "module-path-outside-project",
            "react-project-boundary-invalid",
        }, field

    for field in ("jsxImportSource", "jsxImportSourceTypes"):
        config = dict(original)
        config["compilerOptions"] = {
            **original["compilerOptions"],
            field: "../outside-jsx",
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")

        inspection = _inspect(react_provider, project)

        assert "module-path-outside-project" in {
            diagnostic.code for diagnostic in inspection.diagnostics
        }, field


def test_react_build_rejects_config_escape_before_process_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    inspection = _inspect(react_provider, project)
    config_path = root / "deno.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["imports"]["outside"] = "../outside.ts"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    files = root / ".artifacts" / ".staging" / "boundary" / "files"
    files.mkdir(parents=True)
    report = _build(
        react_provider,
        provider_build_request(
            project,
            inspection,
            files,
            cache_root=root / ".artifacts" / ".cache",
        ),
    )

    assert report.document is None
    assert "module-path-outside-project" in {
        diagnostic.code for diagnostic in report.diagnostics
    }


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_build_rejects_implicit_jsx_module_outside_snapshot(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    source = root / "src" / "App.tsx"
    source.write_text(
        "/** @jsxImportSource ../../outside-jsx */\n"
        "export const App = () => <main>Unsafe</main>;\n",
        encoding="utf-8",
    )
    inspection = _inspect(react_provider, project)
    files = root / ".artifacts" / ".staging" / "pragma" / "files"
    files.mkdir(parents=True)
    outside = files.parent / "outside-jsx"
    outside.mkdir()
    sentinel = outside / "jsx-runtime.ts"
    sentinel.write_text(
        "export const Fragment = Symbol();\n"
        "export const jsx = () => null;\n"
        "export const jsxs = jsx;\n",
        encoding="utf-8",
    )

    report = _build(
        react_provider,
        provider_build_request(
            project,
            inspection,
            files,
            cache_root=root / ".artifacts" / ".cache",
        ),
    )

    assert report.document is None
    assert "module-path-outside-snapshot" in {
        diagnostic.code for diagnostic in report.diagnostics
    }
    assert sentinel.read_text(encoding="utf-8").startswith("export const Fragment")


def test_react_entry_normalization_rewrites_only_the_script_source(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    entry = output / "index-RANDOM.js"
    entry.write_text("console.log('entry');\n", encoding="utf-8")
    unrelated = output / "other.js"
    unrelated.write_text("console.log('other');\n", encoding="utf-8")
    document = """<!doctype html>
<html>
  <body data-entry="index-RANDOM.js">
    <p>index-RANDOM.js and other.js stay here.</p>
    <script data-copy="index-RANDOM.js" SRC='./index-RANDOM.js?mode=dev#entry'></script>
  </body>
</html>
"""
    (output / "index.html").write_text(document, encoding="utf-8")
    digest = hashlib.sha256(entry.read_bytes()).hexdigest()

    _react_build._normalize_entry_name(output)

    normalized = output / f"index-{digest}.js"
    rewritten = (output / "index.html").read_text(encoding="utf-8")
    assert normalized.is_file()
    assert not entry.exists()
    assert unrelated.is_file()
    assert 'data-entry="index-RANDOM.js"' in rewritten
    assert "index-RANDOM.js and other.js stay here." in rewritten
    assert 'data-copy="index-RANDOM.js"' in rewritten
    assert f"SRC='./{normalized.name}?mode=dev#entry'" in rewritten
