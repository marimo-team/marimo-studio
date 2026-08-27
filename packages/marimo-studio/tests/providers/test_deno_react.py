"""Exercise React analysis, containment, build, and determinism."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled.deno_react import build as _react_build
from marimo_studio.view_providers._bundled.deno_react import provider as react_provider
from marimo_studio.view_providers._host import provider_registry

from ..deno_provider_test_support import build_provider as _build
from ..deno_provider_test_support import inspect_provider as _inspect
from ..deno_provider_test_support import project as _project
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
    root, project = _project(tmp_path, react_provider, "react")
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
def test_react_maps_extract_bounded_and_wildcard_mounts(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, react_provider, "react")
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

    assert not inspection.diagnostics
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
    assert "projection-target-unbounded" in {
        item.code for item in _inspect(react_provider, project).diagnostics
    }


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
    root, project = _project(tmp_path, react_provider, "react")
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
    root, project = _project(tmp_path, react_provider, "react")
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
    root, project = _project(tmp_path, react_provider, "react")
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
    root, project = _project(tmp_path, react_provider, "react")
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
    root, project = _project(tmp_path, react_provider, "react")
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
    root, project = _project(tmp_path, react_provider, "react")
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
