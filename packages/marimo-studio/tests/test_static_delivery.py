from __future__ import annotations

import json
import posixpath
import re
import shutil
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import unquote, urlsplit

import marimo_export.delivery as delivery_module
import pytest
from click.testing import CliRunner
from marimo_export import PreparedExport, open_export, verify_export
from marimo_export.descriptors import Provenance, ScalarDescriptor
from marimo_export.index import (
    ExportIndex,
    NotebookProvenance,
    ProducerProvenance,
    StateEntry,
)
from marimo_export.manifest import PreparedManifestLimitError
from marimo_export.wire import canonical_json_sha256, state_fingerprint
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

import marimo_studio._assets as assets_module
import marimo_studio._static_delivery as static_delivery_module
import marimo_studio.export as export_module
from marimo_studio._cli import cli
from marimo_studio._runtime import ZERO_PYTHON_RUNTIME
from marimo_studio._server.presentation import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._server.studio.view_compiler import compile_export_view
from marimo_studio._static_delivery import StaticPublication
from marimo_studio.errors import CompatibilityError, ProtocolError, StaticExportError
from marimo_studio.export import export_view
from marimo_studio.workspace import ensure_view

from .helpers import configured_export_view, replace_app_shell

_CSS_URL = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)")


def _relative_css_assets(stylesheet: str, source: str) -> tuple[str, ...]:
    assets: list[str] = []
    for match in _CSS_URL.finditer(source):
        value = match.group(2).strip()
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith(("/", "#")):
            continue
        relative = posixpath.normpath(
            posixpath.join(posixpath.dirname(stylesheet), unquote(parsed.path))
        )
        if relative == ".." or relative.startswith("../"):
            raise AssertionError(f"Stylesheet URL escapes the runtime closure: {value}")
        assets.append(relative)
    return tuple(assets)


class _FixtureAsset:
    def __init__(self, path: Path) -> None:
        self.path = path

    def close(self) -> None:
        return None


class _FixturePrepared:
    def __init__(self, path: Path, document_sha256: str) -> None:
        self.path = path
        self.identity = open_export(path).identity
        self.plan = SimpleNamespace(inputs=("mode",), document_sha256=document_sha256)
        self.renew_calls = 0
        self.close_calls = 0
        self.asset_calls: list[str] = []
        self.write_calls: list[Path] = []

    def open(self):
        return open_export(self.path)

    def asset(self, relative: str) -> _FixtureAsset:
        self.asset_calls.append(relative)
        return _FixtureAsset(self.path / relative)

    def write(
        self,
        output: Path,
        *,
        replace: bool = False,
        progress: object = None,
    ) -> object:
        assert replace is False
        assert progress is None
        self.write_calls.append(output)
        output.mkdir(parents=True)
        shutil.copy2(self.path / "index.json", output / "index.json")
        return SimpleNamespace(path=output, identity=open_export(output).identity)

    def manifest(
        self,
        export_url: str,
        *,
        state: object = None,
        refresh_interval_ms: int | None = None,
    ) -> dict[str, object]:
        assert state is None
        selected = self.open().default_state
        manifest: dict[str, object] = {
            "schema": "marimo-export.prepared.v1",
            "instance": self.identity,
            "export_url": export_url,
            "inputs": dict(selected.inputs),
            "state_fingerprint": selected.fingerprint,
        }
        if refresh_interval_ms is not None:
            manifest["refresh_interval_ms"] = refresh_interval_ms
        return manifest

    def renew(self) -> None:
        self.renew_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _FixturePublicationSource:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.resolve_calls = 0
        self.timeouts: list[float] = []
        self.prepared: list[_FixturePrepared] = []

    def protected_root(self, notebook: Path) -> Path:
        del notebook
        return self.root

    def resolve(
        self,
        snapshot: PresentationSnapshot,
        *,
        timeout: float = 30.0,
    ) -> StaticPublication:
        self.resolve_calls += 1
        self.timeouts.append(timeout)
        compiled = compile_export_view(snapshot)
        projections = {
            "cells": dict(compiled.bindings.cells),
            "outputs": dict(compiled.bindings.outputs),
            "values": dict(compiled.bindings.values),
        }
        publication = self.root / "prepared" / f"export-{self.resolve_calls}"
        publication.mkdir(parents=True)
        inputs = {"mode": "baseline"}
        fingerprint = state_fingerprint(inputs)
        output_names = tuple(
            sorted(
                {
                    output
                    for bindings in projections.values()
                    for output in bindings.values()
                }
            )
        )
        index = ExportIndex(
            spec_sha256="d" * 64,
            default_state=fingerprint,
            notebook=NotebookProvenance(
                filename=snapshot.resolved.workspace.notebook.name,
                document_sha256=sha256(snapshot.notebook_source.encode()).hexdigest(),
            ),
            producer=ProducerProvenance(
                marimo="0.24.0",
                marimo_export="0.0.0",
                implementation_sha256="c" * 64,
            ),
            inputs=("mode",),
            control_bindings={},
            outputs=output_names,
            aliases={"baseline": fingerprint},
            states={
                fingerprint: StateEntry(
                    inputs=inputs,
                    outputs={
                        name: ScalarDescriptor(
                            value=42,
                            provenance=Provenance(python_type="int"),
                        )
                        for name in output_names
                    },
                )
            },
        )
        publication.joinpath("index.json").write_bytes(index.to_bytes())
        prepared = _FixturePrepared(
            publication,
            index.notebook.document_sha256,
        )
        self.prepared.append(prepared)
        return StaticPublication(
            prepared=cast(PreparedExport, prepared),
            projections=projections,
            view=snapshot.view_name,
            plan_digest=canonical_json_sha256(
                {"inputs": ["mode"], "projections": projections}
            ),
            owner=cast(PreparedExport, prepared),
        )


@pytest.fixture
def static_publication_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _FixturePublicationSource:
    source = _FixturePublicationSource(tmp_path / "publication-store")
    monkeypatch.setattr(static_delivery_module, "publication_source", lambda: source)
    monkeypatch.setattr(delivery_module, "PreparedExport", _FixturePrepared)
    monkeypatch.setattr(
        delivery_module,
        "_materialize_prepared_export",
        lambda prepared, output: prepared.write(output),
    )
    return source


def test_export_view_writes_nested_prepared_export_contract(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view_root = configured_export_view(notebook_path)
    view_root.joinpath("scripts").mkdir()
    view_root.joinpath("scripts/app.js").write_text(
        'document.documentElement.dataset.app = "ready";\n', encoding="utf-8"
    )
    view_root.joinpath("export.yaml").write_text("states: {}\n", encoding="utf-8")
    public = notebook_path.parent / "public"
    public.mkdir()
    public.joinpath("nested").mkdir()
    public.joinpath("nested/data.txt").write_text("public data\n", encoding="utf-8")
    output = tmp_path / "site"
    monkeypatch.setattr(
        export_module,
        "create_export_adapters",
        lambda: pytest.fail(
            "Zero-Python export must not construct WebAssembly adapters"
        ),
    )

    result = export_view(notebook_path, output)

    support = output / "_marimo-studio" / "views" / "dashboard"
    document = result.entrypoint.read_text(encoding="utf-8")
    config = json.loads(support.joinpath("config").read_text(encoding="utf-8"))
    manifest = json.loads(
        support.joinpath("zero-python/current").read_text(encoding="utf-8")
    )
    prepared = manifest["prepared"]
    publication = support / "zero-python" / prepared["instance"]
    closure = assets_module.browser_entry_closure("zero-python")
    closure_files = (closure.script, *closure.styles, *closure.assets)

    assert result.runtime == "zero-python"
    assert closure.file_count == len(closure_files)
    assert closure.total_bytes == sum(path.stat().st_size for path in closure_files)
    assert static_publication_source.resolve_calls == 1
    assert static_publication_source.prepared[0].renew_calls == 3
    assert static_publication_source.prepared[0].close_calls == 1
    assert static_publication_source.prepared[0].asset_calls == []
    assert len(static_publication_source.prepared[0].write_calls) == 1
    assert config["runtime"]["descriptor"] == ZERO_PYTHON_RUNTIME.to_dict()
    assert config["runtime"]["data"] == {
        "manifestUrl": "./_marimo-studio/views/dashboard/zero-python/current",
        "planDigest": manifest["plan_digest"],
    }
    assert config["runtime"]["instance"] == prepared["instance"]
    assert set(config["cellBindings"]) == set(manifest["projections"]["cells"])
    assert manifest["schema"] == "marimo-studio.prepared.v1"
    assert prepared == {
        "schema": "marimo-export.prepared.v1",
        "instance": prepared["instance"],
        "export_url": f"./{prepared['instance']}/",
        "inputs": {"mode": "baseline"},
        "state_fingerprint": state_fingerprint({"mode": "baseline"}),
        "refresh_interval_ms": 0,
    }
    assert manifest["document_sha256"] == sha256(notebook_path.read_bytes()).hexdigest()
    assert manifest["view"] == "dashboard"
    assert len(manifest["plan_digest"]) == 64
    assert set(manifest["projections"]) == {"values", "outputs", "cells"}
    assert publication.joinpath("index.json").is_file()
    verification = verify_export(publication)
    assert verification.states == 1
    assert verification.outputs == 3
    assert document.count('src="./_marimo-studio/assets/zero-python.js"') == 1
    assert 'src="./_marimo-studio/assets/runtime.js"' not in document
    assert output.joinpath("scripts/app.js").is_file()
    assert not output.joinpath("export.yaml").exists()
    assert output.joinpath("public/nested/data.txt").is_file()
    notebook_source = notebook_path.read_bytes()
    assert all(
        notebook_source not in path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    )


def test_zero_python_rejects_tampered_patch_metadata_before_staging(
    notebook_path: Path,
    runtime_assets: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_export_view(notebook_path)
    assets = tmp_path / "browser"
    shutil.copytree(runtime_assets, assets)
    metadata_path = assets / "build-meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["marimo"]["patchSha256"] = "tampered"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)
    monkeypatch.setattr(
        export_module,
        "stage",
        lambda *_args, **_kwargs: pytest.fail("staging must not begin"),
    )
    output = tmp_path / "site"

    with pytest.raises(CompatibilityError, match="browser runtime"):
        export_view(notebook_path, output)

    assert static_publication_source.resolve_calls == 0
    assert not output.exists()
    assert not tmp_path.joinpath("cell-executed").exists()


def test_export_view_passes_the_zero_python_preparation_timeout(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
) -> None:
    configured_export_view(notebook_path)

    export_view(notebook_path, tmp_path / "site", timeout=75.0)

    assert static_publication_source.timeouts == [75.0]


def test_static_manifest_rejects_three_hundred_large_hosts(
    notebook_path: Path,
    static_publication_source: _FixturePublicationSource,
) -> None:
    configured_export_view(notebook_path)
    source = static_publication_source.resolve(
        NotebookPresentation(notebook_path).snapshot("dashboard")
    )
    publication = StaticPublication(
        prepared=source.prepared,
        projections={
            "cells": {},
            "outputs": {},
            "values": {
                f"host-{index}-{'h' * 900}": f"value:{index}-{'o' * 240}"
                for index in range(300)
            },
        },
        view=source.view,
        plan_digest=source.plan_digest,
        owner=source.owner,
    )
    try:
        with pytest.raises(PreparedManifestLimitError, match="262144-byte limit"):
            publication.manifest("./prepared/")
    finally:
        publication.owner.close()


def test_static_export_preserves_bundle_failure_when_resource_close_fails(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_export_view(notebook_path)

    def fail_bundle(*_args: object, **_kwargs: object):
        raise StaticExportError("bundle failed")

    def fail_close(prepared: _FixturePrepared) -> None:
        prepared.close_calls += 1
        raise RuntimeError("close failed")

    monkeypatch.setattr(export_module, "_write_bundle", fail_bundle)
    monkeypatch.setattr(_FixturePrepared, "close", fail_close)

    with pytest.raises(StaticExportError, match="bundle failed") as raised:
        export_view(notebook_path, tmp_path / "site")

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "close failed"
    assert static_publication_source.prepared[0].close_calls == 1


@pytest.mark.usefixtures("static_publication_source")
def test_zero_python_styles_are_served_from_a_nested_deployment(
    notebook_path: Path,
    runtime_assets: Path,
    tmp_path: Path,
) -> None:
    configured_export_view(notebook_path)
    output = tmp_path / "site"
    export_view(notebook_path, output)
    closure = assets_module.browser_entry_closure("zero-python")
    deployed_assets = output / "_marimo-studio" / "assets"
    document = output.joinpath("index.html").read_text(encoding="utf-8")
    runtime_script = deployed_assets.joinpath("zero-python.js").read_text(
        encoding="utf-8"
    )
    app = Starlette(
        routes=[
            Mount(
                "/nested/deployment",
                app=StaticFiles(directory=output, html=True),
            )
        ]
    )

    with TestClient(app) as client:
        entry = client.get("/nested/deployment/_marimo-studio/assets/zero-python.js")
        assert entry.status_code == 200
        assert entry.content == closure.script.read_bytes()
        for style in closure.styles:
            relative = style.relative_to(runtime_assets).as_posix()
            assert f'"./{relative}"' in runtime_script
            assert f'href="./_marimo-studio/assets/{relative}"' in document
            response = client.get(
                f"/nested/deployment/_marimo-studio/assets/{relative}"
            )
            assert response.status_code == 200
            for asset in _relative_css_assets(relative, response.text):
                assert deployed_assets.joinpath(asset).is_file(), (relative, asset)
                assert (
                    client.get(
                        f"/nested/deployment/_marimo-studio/assets/{asset}"
                    ).status_code
                    == 200
                )


@pytest.mark.parametrize(
    "forbidden",
    (
        "chunks/server-runtime.js",
        "chunks/pyodide-worker.js",
        "chunks/wasm-runtime.js",
        "chunks/websocket-client.js",
        "chunks/notebook-source.js",
        "chunks/notebook-code.js",
    ),
)
def test_zero_python_entry_closure_rejects_execution_assets(
    runtime_assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forbidden: str,
) -> None:
    assets = tmp_path / "browser"
    shutil.copytree(runtime_assets, assets)
    manifest_path = assets / "entry-closures.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"]["zero-python"]["assets"].append(forbidden)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)

    with pytest.raises(ProtocolError, match="forbidden runtime asset"):
        assets_module.browser_entry_closure("zero-python")


def test_wasm_entry_closure_rejects_zero_python_assets(
    runtime_assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = tmp_path / "browser"
    shutil.copytree(runtime_assets, assets)
    assets.joinpath("zero-python/runtime.js").parent.mkdir()
    assets.joinpath("zero-python/runtime.js").write_text("", encoding="utf-8")
    manifest_path = assets / "entry-closures.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"]["runtime"]["assets"].append("zero-python/runtime.js")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)

    with pytest.raises(ProtocolError, match="Zero-Python runtime asset"):
        assets_module.browser_entry_closure("runtime")


@pytest.mark.parametrize("invalid", ("duplicate", "script-suffix", "style-suffix"))
def test_browser_entry_closure_validates_file_categories(
    runtime_assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    assets = tmp_path / "browser"
    shutil.copytree(runtime_assets, assets)
    manifest_path = assets / "entry-closures.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"]["zero-python"]
    if invalid == "duplicate":
        entry["assets"].append(entry["styles"][0])
        message = "duplicate paths"
    elif invalid == "script-suffix":
        assets.joinpath("zero-python.txt").write_text("entry", encoding="utf-8")
        entry["script"] = "zero-python.txt"
        message = "script must use .js"
    else:
        assets.joinpath("zero-python.txt").write_text("style", encoding="utf-8")
        entry["styles"] = ["zero-python.txt"]
        message = "styles must use .css"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: assets)

    with pytest.raises(ProtocolError, match=message):
        assets_module.browser_entry_closure("zero-python")


def test_zero_python_export_detects_a_saved_spec_change(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view_root = configured_export_view(notebook_path)
    saved_spec = view_root / "export.yaml"
    saved_spec.write_text("states: {}\n", encoding="utf-8")
    stable = export_module._delivery_sources_stable

    def change_spec(delivery: export_module._PreparedDelivery) -> bool:
        saved_spec.write_text("states: {changed: {}}\n", encoding="utf-8")
        return stable(delivery)

    monkeypatch.setattr(export_module, "_delivery_sources_stable", change_spec)
    output = tmp_path / "site"

    with pytest.raises(StaticExportError, match="sources changed"):
        export_view(notebook_path, output)

    assert not output.exists()
    assert static_publication_source.prepared[0].close_calls == 1


def test_failed_bundle_verification_preserves_existing_output(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_export_view(notebook_path)
    output = tmp_path / "site"
    output.mkdir()
    output.joinpath("existing.txt").write_text("stable", encoding="utf-8")
    write_prepared = _FixturePrepared.write

    def corrupt_materialized(
        prepared: _FixturePrepared,
        destination: Path,
        *,
        replace: bool = False,
        progress: object = None,
    ) -> object:
        result = write_prepared(
            prepared,
            destination,
            replace=replace,
            progress=progress,
        )
        destination.joinpath("index.json").write_text("fixture corruption")
        return result

    monkeypatch.setattr(_FixturePrepared, "write", corrupt_materialized)

    with pytest.raises(
        StaticExportError,
        match=r"Could not commit.*invalid export index",
    ):
        export_view(notebook_path, output, force=True)

    assert output.joinpath("existing.txt").read_text(encoding="utf-8") == "stable"
    assert not output.joinpath("index.html").exists()
    assert static_publication_source.prepared[0].close_calls == 1


@pytest.mark.usefixtures("static_publication_source")
def test_zero_python_export_uses_the_shared_force_commit(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configured_export_view(notebook_path)
    output = tmp_path / "site"
    export_view(notebook_path, output)
    output.joinpath("stale.txt").write_text("stale", encoding="utf-8")

    export_view(notebook_path, output, force=True)

    assert not output.joinpath("stale.txt").exists()
    assert output.joinpath("index.html").is_file()


def test_export_command_writes_projection_free_view_as_plain_static_files(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = ensure_view(notebook_path)
    template = setup.root / "index.html"
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8").replace(
                "</head>",
                '<script type="module" src="pure.js"></script>\n  </head>',
            ),
            '<article id="pure-view"><h1>Authored report</h1></article>',
        ),
        encoding="utf-8",
    )
    setup.root.joinpath("pure.js").write_text(
        'document.documentElement.dataset.pure = "ready";\n',
        encoding="utf-8",
    )
    public = notebook_path.parent / "public"
    public.mkdir()
    public.joinpath("report.txt").write_text("published\n", encoding="utf-8")
    authored = template.read_text(encoding="utf-8")
    output = tmp_path / "site"
    monkeypatch.setattr(
        static_delivery_module,
        "publication_source",
        lambda: pytest.fail("a projection-free view must not prepare an export"),
    )
    monkeypatch.setattr(
        export_module,
        "create_export_adapters",
        lambda: pytest.fail("a projection-free view must not construct adapters"),
    )
    monkeypatch.setattr(
        assets_module,
        "browser_entry_closure",
        lambda _name: pytest.fail("a projection-free view has no runtime closure"),
    )

    result = CliRunner().invoke(
        cli,
        [
            "export",
            str(notebook_path),
            "--output",
            str(output),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["runtime"] == "zero-python"
    assert output.joinpath("index.html").read_text(encoding="utf-8") == authored
    assert output.joinpath("pure.js").is_file()
    assert output.joinpath("app.css").is_file()
    assert output.joinpath("public/report.txt").read_text(encoding="utf-8") == (
        "published\n"
    )
    assert output.joinpath(".nojekyll").is_file()
    assert not output.joinpath("_marimo-studio").exists()


def test_export_command_reports_the_static_entrypoint(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
) -> None:
    configured_export_view(notebook_path)
    output = tmp_path / "site"

    result = CliRunner().invoke(
        cli,
        [
            "export",
            str(notebook_path),
            "--output",
            str(output),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == 1
    assert payload["view"] == "dashboard"
    assert payload["runtime"] == "zero-python"
    assert Path(payload["entrypoint"]) == output / "index.html"
    assert output.joinpath("index.html").is_file()
    assert result.stderr == ""


def test_export_command_passes_the_zero_python_preparation_timeout(
    notebook_path: Path,
    tmp_path: Path,
    static_publication_source: _FixturePublicationSource,
) -> None:
    configured_export_view(notebook_path)

    result = CliRunner().invoke(
        cli,
        [
            "export",
            str(notebook_path),
            "--output",
            str(tmp_path / "site"),
            "--timeout",
            "75",
        ],
    )

    assert result.exit_code == 0, result.output
    assert static_publication_source.timeouts == [75.0]
