from __future__ import annotations

import json
import math
import os
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlsplit

import pytest

import marimo_studio._delivery.assets as assets_module
import marimo_studio._delivery.export as export_module
import marimo_studio._delivery.runtime_config as runtime_config_module
from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._composition import create_browser_runtime_projector
from marimo_studio._delivery.browser_ports import (
    BrowserRuntimeCell,
    BrowserRuntimeProjection,
)
from marimo_studio._delivery.export import export_view
from marimo_studio._delivery.ports import ExportAdapters, StaticRuntimeConfig
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._workspace import load_studio
from marimo_studio.errors import (
    RuntimeConfigTooLargeError,
    StaticExportError,
    ViewProjectError,
)
from marimo_studio.errors._internal import CompatibilityError
from marimo_studio.view_providers import BuildProfile, ViewProject

from ..artifact_test_support import add_provider_outputs
from ..helpers import replace_app_shell
from .export_test_support import configure_export_view


class _DocumentResources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.base: str | None = None
        self.references: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "base":
            self.base = attributes.get("href")
        elif tag == "script":
            reference = attributes.get("src")
            if reference:
                self.references.append(reference)
        elif tag == "link" and "stylesheet" in (attributes.get("rel") or "").split():
            reference = attributes.get("href")
            if reference:
                self.references.append(reference)


def _assert_document_resources_resolve(document: Path) -> None:
    parser = _DocumentResources()
    parser.feed(document.read_text(encoding="utf-8"))
    assert parser.base is not None
    for reference in parser.references:
        parsed = urlsplit(reference)
        if not parsed.scheme and not parsed.netloc:
            assert document.parent.joinpath(parsed.path).is_file(), reference


def test_export_view_writes_a_complete_static_bundle(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    view_root = configure_export_view(notebook_path)
    public = notebook_path.parent / "public"
    public.mkdir()
    public.joinpath("sample.txt").write_text("public asset", encoding="utf-8")
    view_root.joinpath("app.js").write_text("source-only", encoding="utf-8")
    template = view_root / "index.html"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "</head>",
            '<script type="module">window.message = "ready";</script>\n  </head>',
        ),
        encoding="utf-8",
    )
    output = tmp_path / "site"

    result = export_view(notebook_path, output, runtime="wasm")

    config = json.loads(
        output.joinpath("_marimo-studio/views/dashboard/config").read_text(
            encoding="utf-8"
        )
    )
    assert result.view == "dashboard"
    assert result.output == output
    assert result.files == sum(1 for path in output.rglob("*") if path.is_file())
    assert config["runtime"]["id"] == "wasm"
    assert config["rootUrl"] == "./"
    assert config["publicRootUrl"] == "./"
    assert config["supportUrl"] == "./_marimo-studio/views/dashboard"
    assert config["showCellLogs"] is load_studio(notebook_path).show_cell_logs
    assert config["projectionTargets"]["cells"]["cell-2"]["status"] == "ready"
    assert config["projectionTargets"]["variables"]["doubled"]["status"] == "ready"
    assert {site["kind"] for site in config["mounts"]} == {
        "cell",
        "output",
        "value",
    }
    assert config["runtimeBindings"]["cellRefs"]
    runtime_data = config["runtime"]["data"]
    assert runtime_data["bootstrapCellId"] in {
        cell["id"] for cell in runtime_data["executionCells"]
    }
    code = runtime_data["code"]
    compile(code, "notebook.py", "exec")
    _assert_document_resources_resolve(result.entrypoint)
    assert not output.joinpath("_marimo-studio/views/dashboard/cells").exists()
    assert not output.joinpath("app.js").exists()
    assert (
        output.joinpath("public/sample.txt").read_bytes()
        == public.joinpath("sample.txt").read_bytes()
    )
    assert output.joinpath("_marimo-studio/assets/runtime.js").is_file()
    assert output.joinpath(".nojekyll").is_file()


def test_zero_python_export_combines_the_view_and_prepared_publication(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "prepared-site"

    result = export_view(notebook_path, output, runtime="zero-python")

    support = output / "_marimo-studio" / "views" / "dashboard"
    config = json.loads(support.joinpath("config").read_text(encoding="utf-8"))
    manifest = json.loads(
        support.joinpath("zero-python/current").read_text(encoding="utf-8")
    )
    instance = manifest["prepared"]["instance"]
    assert result.runtime == "zero-python"
    assert result.cache_activity is not None
    assert result.entrypoint.is_file()
    assert config["runtime"]["id"] == "zero-python"
    assert config["runtime"]["instance"] == instance
    assert support.joinpath("zero-python", instance, "index.json").is_file()
    assert output.joinpath("_marimo-studio/assets/zero-python.js").is_file()
    assert not output.joinpath("_marimo-studio/assets/runtime.js").exists()


def test_zero_python_export_reuses_the_prepared_generation(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    first_output = tmp_path / "prepared-site-first"
    repeated_output = tmp_path / "prepared-site-repeated"

    export_view(notebook_path, first_output, runtime="zero-python")
    export_view(notebook_path, repeated_output, runtime="zero-python")
    first_manifest = json.loads(
        first_output.joinpath(
            "_marimo-studio/views/dashboard/zero-python/current"
        ).read_text(encoding="utf-8")
    )
    repeated_manifest = json.loads(
        repeated_output.joinpath(
            "_marimo-studio/views/dashboard/zero-python/current"
        ).read_text(encoding="utf-8")
    )

    assert (
        repeated_manifest["prepared"]["instance"]
        == first_manifest["prepared"]["instance"]
    )


def test_wasm_export_rejects_prepare_timeout_before_loading_target(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="prepare_timeout is only valid when runtime is 'zero-python'",
    ):
        export_view(
            tmp_path / "missing.py",
            tmp_path / "site",
            runtime="wasm",
            prepare_timeout=10,
        )


@pytest.mark.parametrize(
    "prepare_timeout",
    (True, 0, -1, math.nan, math.inf, "30"),
)
def test_zero_python_export_rejects_invalid_prepare_timeout_before_loading_target(
    tmp_path: Path,
    prepare_timeout: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="prepare_timeout must be a finite positive number",
    ):
        export_view(
            tmp_path / "missing.py",
            tmp_path / "site",
            runtime="zero-python",
            prepare_timeout=cast(float | None, prepare_timeout),
        )


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
@pytest.mark.parametrize("swap", ("leaf", "parent"))
def test_export_public_assets_reject_symlink_swaps(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap: str,
) -> None:
    configure_export_view(notebook_path)
    public = notebook_path.parent / "public"
    nested = public / "nested"
    nested.mkdir(parents=True)
    source = nested / "sample.txt"
    source.write_text("public asset", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_source = outside / "sample.txt"
    outside_source.write_text("outside asset", encoding="utf-8")
    open_file = export_module.SecureDirectory.open_file
    swapped = False

    def swap_before_open(
        filesystem: export_module.SecureDirectory,
        path: Path,
        flags: int = os.O_RDONLY,
    ) -> int:
        nonlocal swapped
        if (
            filesystem.root == public.absolute()
            and path.name == "sample.txt"
            and not swapped
        ):
            swapped = True
            if swap == "leaf":
                source.rename(nested / "retired.txt")
                source.symlink_to(outside_source)
            else:
                nested.rename(public / "retired")
                nested.symlink_to(outside, target_is_directory=True)
        return open_file(filesystem, path, flags)

    monkeypatch.setattr(export_module.SecureDirectory, "open_file", swap_before_open)
    output = tmp_path / "site"

    with pytest.raises(StaticExportError, match="static export source"):
        export_view(notebook_path, output, runtime="wasm")

    assert swapped
    assert not output.exists()


def test_export_preserves_nested_vanilla_local_sources(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    source_root = configure_export_view(notebook_path)
    pages = source_root / "pages"
    pages.mkdir()
    nested_document = pages / "index.html"
    nested_document.write_text(
        source_root.joinpath("index.html")
        .read_text(encoding="utf-8")
        .replace(
            "</head>",
            '<link rel="stylesheet" href="./app.css?theme=nested">\n'
            '<script type="module" src="./app.js#boot"></script></head>',
        ),
        encoding="utf-8",
    )
    (pages / "app.js").write_text('window.nestedAsset = "ready";\n', encoding="utf-8")
    (pages / "app.css").write_text("body { color: canvastext; }\n", encoding="utf-8")
    (pages / "unused.js").write_text("throw new Error();\n", encoding="utf-8")
    source_root.joinpath("index.html").write_text(
        "<!doctype html><title>Independent root asset</title>\n",
        encoding="utf-8",
    )
    manifest = source_root / "view.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '\n[options]\nentrypoint = "pages/index.html"\n',
        encoding="utf-8",
    )
    output = tmp_path / "site"

    result = export_view(notebook_path, output, runtime="zero-python")

    config = json.loads(
        output.joinpath("_marimo-studio/views/dashboard/config").read_text(
            encoding="utf-8"
        )
    )
    assert result.document.as_posix() == "pages/index.html"
    assert result.entrypoint == output / "pages" / "index.html"
    _assert_document_resources_resolve(result.entrypoint)
    assert config["rootUrl"] == "../"
    assert config["publicRootUrl"] == "../"
    assert config["supportUrl"] == "../_marimo-studio/views/dashboard"
    assert (
        output.joinpath("pages/app.js").read_bytes()
        == pages.joinpath("app.js").read_bytes()
    )
    assert (
        output.joinpath("pages/app.css").read_bytes()
        == pages.joinpath("app.css").read_bytes()
    )
    assert not output.joinpath("pages/unused.js").exists()
    assert not output.joinpath("index.html").exists()


def test_export_rejects_unlisted_artifact_files(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    publish = export_module.publish_view

    def publish_with_extra_file(
        project: ViewProject,
        profile: BuildProfile,
        *,
        expected_generation: str | None = None,
    ) -> ArtifactLease:
        lease = publish(
            project,
            profile,
            expected_generation=expected_generation,
        )
        lease.artifact.root.joinpath("unlisted.js").write_text(
            "unlisted",
            encoding="utf-8",
        )
        return lease

    monkeypatch.setattr(export_module, "publish_view", publish_with_extra_file)
    output = tmp_path / "site"

    with pytest.raises(StaticExportError, match="file tree"):
        export_view(notebook_path, output, runtime="wasm")

    assert not output.exists()


def test_export_rejects_artifact_tampering_during_copy(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    read_bytes = ArtifactLease.read_bytes
    tampered = False

    def read_then_tamper(
        lease: ArtifactLease,
        path: str | PurePosixPath,
    ) -> bytes:
        nonlocal tampered
        payload = read_bytes(lease, path)
        relative = PurePosixPath(path)
        if relative == PurePosixPath("index.html") and not tampered:
            tampered = True
            lease.artifact.root.joinpath(*relative.parts).write_bytes(
                b"x" * len(payload)
            )
        return payload

    monkeypatch.setattr(ArtifactLease, "read_bytes", read_then_tamper)
    output = tmp_path / "site"

    with pytest.raises(StaticExportError, match="sources changed"):
        export_view(notebook_path, output, runtime="wasm")

    assert tampered
    assert not output.exists()


def test_export_surfaces_provider_process_cleanup_failure(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)

    def fail_inspection(*_args: object) -> object:
        try:
            raise ProcessCleanupError("export provider process survived")
        except ProcessCleanupError as cleanup:
            raise ViewProjectError("provider inspection failed") from cleanup

    monkeypatch.setattr(export_module, "inspect_view_project_sync", fail_inspection)

    with pytest.raises(
        ProcessCleanupError,
        match="export provider process survived",
    ):
        export_view(notebook_path, tmp_path / "site", runtime="wasm")


def test_export_revision_changes_with_runtime_configuration(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    adapters = export_module.create_export_adapters()
    theme = {"value": "light"}
    monkeypatch.setattr(
        export_module,
        "create_export_adapters",
        lambda: ExportAdapters(
            browser=adapters.browser,
            runtime_config=lambda notebook: StaticRuntimeConfig(
                user={
                    "display": {"theme": theme["value"]},
                    "completion": {"codeium_api_key": "leak-static-completion"},
                    "ai": {"open_ai": {"api_key": "leak-static-ai"}},
                    "mcp": {
                        "mcpServers": {
                            "private": {
                                "env": {"TOKEN": "leak-static-mcp-env"},
                                "headers": {"Authorization": "leak-static-mcp-header"},
                            }
                        }
                    },
                },
                overrides={
                    "runtime": {
                        "show_tracebacks": True,
                        "dotenv": ["leak-static-dotenv"],
                    }
                },
            ),
        ),
    )
    output = tmp_path / "site"
    export_view(notebook_path, output, runtime="wasm")
    config_path = output / "_marimo-studio/views/dashboard/config"
    before = json.loads(config_path.read_text(encoding="utf-8"))

    theme["value"] = "dark"
    export_view(notebook_path, output, runtime="wasm", force=True)
    after = json.loads(config_path.read_text(encoding="utf-8"))

    assert before["userConfig"] == {"display": {"theme": "light"}}
    assert after["userConfig"] == {"display": {"theme": "dark"}}
    assert before["configOverrides"] == {"runtime": {"show_tracebacks": True}}
    assert before["revision"] != after["revision"]
    assert before["runtime"] == after["runtime"]
    assert before["projectionTargets"] == after["projectionTargets"]


def test_static_export_enforces_the_shared_encoded_byte_budget(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"
    monkeypatch.setattr(runtime_config_module, "RUNTIME_CONFIG_MAX_BYTES", 1)

    with pytest.raises(RuntimeConfigTooLargeError) as raised:
        export_view(notebook_path, output, runtime="wasm")

    assert raised.value.size > 1
    assert raised.value.limit == 1
    assert not output.exists()


def test_export_rejects_browser_release_drift_before_creating_output(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"
    release = create_browser_runtime_projector()
    monkeypatch.setattr(
        assets_module,
        "_runtime_marimo_metadata",
        lambda: {
            "version": release.version,
            "commit": "different",
        },
    )

    with pytest.raises(CompatibilityError, match="browser runtime"):
        export_view(notebook_path, output, runtime="wasm")

    assert not output.exists()


def test_export_uses_the_composed_browser_projection(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"
    release = create_browser_runtime_projector()

    class Projector:
        version = release.version
        commit = release.commit

        def project(
            self, *_args: object, **_kwargs: object
        ) -> BrowserRuntimeProjection:
            return BrowserRuntimeProjection(
                instance="composed-instance",
                version=self.version,
                commit=self.commit,
                code="# composed browser projection\n",
                execution_cells=(BrowserRuntimeCell("bootstrap", "register_bridge()"),),
                bootstrap_cell_id="bootstrap",
            )

    monkeypatch.setattr(
        export_module,
        "create_export_adapters",
        lambda: ExportAdapters(
            browser=Projector(),
            runtime_config=lambda notebook: StaticRuntimeConfig(
                user={},
                overrides={},
            ),
        ),
    )

    export_view(notebook_path, output, runtime="wasm")

    config = json.loads(
        output.joinpath("_marimo-studio/views/dashboard/config").read_text(
            encoding="utf-8"
        )
    )
    assert config["runtime"]["instance"] == "composed-instance"
    runtime = config["runtime"]["data"]
    assert runtime["code"] == "# composed browser projection\n"
    assert runtime["executionCells"] == [
        {"id": runtime["bootstrapCellId"], "code": "register_bridge()"}
    ]


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("_MARIMO-STUDIO/assets/runtime.js", "reserved Studio route"),
        (".nojekyll", "owned by both"),
    ],
)
def test_export_view_rejects_view_assets_that_collide_with_generated_paths(
    notebook_path: Path,
    tmp_path: Path,
    relative: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view_root = configure_export_view(notebook_path)
    project = load_studio(notebook_path).view("dashboard")
    add_provider_outputs(
        monkeypatch,
        project,
        {PurePosixPath(relative): b"collision"},
    )
    entry = view_root / "index.html"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(StaticExportError, match=message):
        export_view(notebook_path, tmp_path / "site", runtime="wasm")

    assert not (tmp_path / "site").exists()


def test_export_view_reports_unresolved_projections_before_writing(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    view_root = configure_export_view(notebook_path)
    template = view_root / "index.html"
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            '<marimo-cell name="missing"></marimo-cell>',
        ),
        encoding="utf-8",
    )
    output = tmp_path / "site"

    with pytest.raises(StaticExportError, match="unresolved projections") as error:
        export_view(notebook_path, output, runtime="wasm")

    assert (
        f"marimo-studio validate dashboard --target {notebook_path} --level static"
        in str(error.value)
    )
    assert not output.exists()
