"""Exercise React analysis, containment, build, and determinism."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled.deno_react import build as _react_build
from marimo_studio.view_providers._bundled.deno_react import provider as react_provider
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

    assert [site.allowed_targets for site in inspection.mounts] == [
        ("controls",),
        ("controls",),
    ]
    assert len({site.id for site in inspection.mounts}) == 2

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
    padded_sites = _inspect(react_provider, project).mounts
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
    canonical_sites = _inspect(react_provider, project).mounts

    assert {site.kind: site.allowed_targets for site in padded_sites} == {
        "cell": ("controls",),
        "output": ("summary",),
        "value": ("report.total",),
    }
    assert {site.kind: site.id for site in padded_sites} == {
        site.kind: site.id for site in canonical_sites
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
    assert conflict.mounts == ()


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_react_default_starter_declares_notebook_cell_targets(
    tmp_path: Path,
) -> None:
    _root, project = _project(tmp_path, react_provider, "marimo-studio/react")

    inspection = _inspect(react_provider, project)

    assert [(site.kind, site.allowed_targets) for site in inspection.mounts] == [
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
    assert inspection.mounts == ()


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
    assert inspection.mounts == ()
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
def test_react_starter_types_projections_and_exposes_guidance(
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
        {error ? "Unavailable" : value?.get(0)?.label ?? sourceBytes ?? 0}
      </output>
      <marimo-cell name="summary" />
      <marimo-output value="rows" />
    </main>
  );
};
""",
        encoding="utf-8",
    )
    (root / "DESIGN.md").write_text("# Page design\n", encoding="utf-8")
    inspection = _inspect(react_provider, project)
    files = root / ".artifacts" / ".staging" / "typed-starter" / "files"
    files.mkdir(parents=True)

    report = _build(
        react_provider,
        provider_build_request(project, inspection, files),
    )

    guidance = {
        item.path.as_posix(): item
        for item in inspection.editor_documents
        if item.path.as_posix() in {"AGENTS.md", "DESIGN.md"}
    }
    assert {path: (item.language, item.access) for path, item in guidance.items()} == {
        "AGENTS.md": ("markdown", "edit"),
        "DESIGN.md": ("markdown", "edit"),
    }
    assert report.document is not None


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

    assert [(site.kind, site.allowed_targets) for site in inspection.mounts] == [
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

    assert [site.kind for site in inspection.mounts] == [
        "cell",
        "cell",
        "cell",
        "value",
        "output",
    ]
    assert [site.allowed_targets for site in inspection.mounts] == [
        ("overview", "detail"),
        ("imported", "detail"),
        None,
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


@pytest.mark.parametrize(
    ("entrypoint", "code"),
    (
        ("src/custom.html", "react-entrypoint-unsupported"),
        ("../outside.html", "provider-options-invalid"),
    ),
)
def test_react_inspection_reports_one_entrypoint_contract_diagnostic(
    tmp_path: Path,
    entrypoint: str,
    code: str,
) -> None:
    root, project = _project(tmp_path, react_provider, "marimo-studio/react")
    if entrypoint == "src/custom.html":
        (root / "src" / "custom.html").write_text(
            (root / "src" / "index.html").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    project = replace(
        project,
        options={**project.options, "entrypoint": entrypoint},
    )

    inspection = _inspect(provider_registry().get(project.provider), project)

    assert [item.code for item in inspection.diagnostics].count(code) == 1
    assert all(
        document.path.as_posix() != "view.toml"
        for document in inspection.editor_documents
    )


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
