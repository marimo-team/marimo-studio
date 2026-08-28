"""Protect the compact provider extension boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

from marimo_studio._artifacts.inputs import project_input_paths
from marimo_studio._artifacts.limits import FileBudget
from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildResult,
    MountDeclaration,
    ProjectDiagnostic,
    ProjectInput,
    ProviderInfo,
    SourceDocument,
    SourceLocation,
    StarterContext,
    ViewProject,
)
from marimo_studio.view_providers._host import conformance as conformance_module
from marimo_studio.view_providers._host.registry import (
    ProviderRegistry,
)
from marimo_studio.view_providers._validation import validate_relative_path

from ..provider_test_support import (
    ProviderStub,
    candidate,
    inspection,
    provider_build_request,
)

pytestmark = pytest.mark.supported_python


@pytest.mark.parametrize(
    "path",
    (
        "",
        "../outside",
        "/absolute",
        "C:/windows",
        "folder//file",
        "folder/./file",
        "folder\\file",
        "folder/\u0000file",
        "cafe\u0301.txt",
        "CON",
        "nested/prn.txt",
        "AUX.json",
        "COM1.js",
        "LPT9/style.css",
        "trailing.",
        "nested/trailing ",
        "question?.js",
        'quote".html',
        "pipe|.css",
        "star*.js",
        "less<.html",
        "greater>.html",
        "colon:name.js",
    ),
)
def test_provider_paths_reject_noncanonical_project_locations(path: str) -> None:
    with pytest.raises(ValueError):
        validate_relative_path(path, field="test path")


def test_provider_info_contains_only_discovery_contracts() -> None:
    info = ProviderInfo(
        title="Reports",
        summary="Builds report frontends.",
        api_version=4,
    )

    assert info.to_dict() == {
        "schema": 1,
        "title": "Reports",
        "summary": "Builds report frontends.",
        "api_version": PROVIDER_API_VERSION,
    }


def test_project_inspection_separates_editor_documents_from_build_inputs() -> None:
    payload = inspection().to_dict()

    assert payload["editor_documents"] == [
        {
            "path": "index.html",
            "language": "html",
            "access": "edit",
            "label": None,
        }
    ]
    assert payload["input_scope"] == [
        {"path": "index.html", "kind": "file"},
        {"path": "view.toml", "kind": "file"},
    ]


def test_input_scope_excludes_undeclared_dependency_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "view"
    source = root / "src" / "App.tsx"
    dependency = root / "node_modules" / "package" / "index.js"
    source.parent.mkdir(parents=True)
    dependency.parent.mkdir(parents=True)
    source.write_text("export default 1;\n", encoding="utf-8")
    dependency.write_text("generated dependency\n", encoding="utf-8")
    manifest = root / "view.toml"
    manifest.write_text("schema = 1\n", encoding="utf-8")
    project = ViewProject("dashboard", root, manifest, "example/report", {})
    selected = replace(
        inspection(),
        editor_documents=(SourceDocument(PurePosixPath("src/App.tsx"), "tsx", "edit"),),
        input_scope=(
            ProjectInput(PurePosixPath("src"), "directory"),
            ProjectInput(PurePosixPath("view.toml"), "file"),
        ),
    )

    assert project_input_paths(project, selected) == (
        PurePosixPath("src/App.tsx"),
        PurePosixPath("view.toml"),
    )


@pytest.mark.parametrize(
    "files",
    (
        {PurePosixPath("view.toml"): b"owned by core"},
        {PurePosixPath(".artifacts/file"): b"generated"},
        {
            PurePosixPath("App.tsx"): b"one",
            PurePosixPath("app.tsx"): b"two",
        },
        {
            PurePosixPath("src"): b"file",
            PurePosixPath("src/app.tsx"): b"child",
        },
    ),
)
def test_starter_files_cannot_claim_core_or_ambiguous_paths(
    files: dict[PurePosixPath, bytes],
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.plan = files
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])

    with pytest.raises(ConfigurationError, match=r"reserves|colliding|overlapping"):
        installed.create(
            provider.starter,
            StarterContext("dashboard", "notebook"),
        )


def test_provider_cannot_expose_the_core_manifest_in_the_editor(
    tmp_path: Path,
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.inspection = replace(
        inspection(),
        editor_documents=(SourceDocument(PurePosixPath("view.toml"), "toml", "edit"),),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match=r"cannot expose.*view.toml"):
        installed.inspect(inspection_request(project))


def test_provider_inspection_cache_stays_outside_the_view_project(
    tmp_path: Path,
) -> None:
    provider = ProviderStub("example/html", "html")
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match=r"cache outside the view project"):
        installed.inspect(
            inspection_request(
                project,
                cache_root=root / ".artifacts" / ".cache",
            )
        )


def test_editor_documents_can_stay_outside_build_inputs(tmp_path: Path) -> None:
    provider = ProviderStub("example/html", "html")
    provider.inspection = replace(
        inspection(),
        editor_documents=(
            SourceDocument(PurePosixPath("index.html"), "html", "edit"),
            SourceDocument(PurePosixPath("AGENTS.md"), "markdown", "edit"),
        ),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {},
    )
    project.manifest.write_text("schema = 1\n", encoding="utf-8")
    project.root.joinpath("index.html").write_text("<main></main>", encoding="utf-8")
    project.root.joinpath("AGENTS.md").write_text(
        "# Provider instructions\n", encoding="utf-8"
    )

    accepted = installed.inspect(inspection_request(project))

    assert [document.path for document in accepted.editor_documents] == [
        PurePosixPath("index.html"),
        PurePosixPath("AGENTS.md"),
    ]
    assert project_input_paths(project, accepted) == (
        PurePosixPath("index.html"),
        PurePosixPath("view.toml"),
    )


def test_provider_diagnostics_accept_the_manifest_but_reject_undeclared_sources(
    tmp_path: Path,
) -> None:
    provider = ProviderStub("example/html", "html")
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "dashboard",
        root,
        root / "view.toml",
        installed.key,
        {},
    )
    project.manifest.write_text("schema = 1\n", encoding="utf-8")
    project.root.joinpath("index.html").write_text("<main></main>", encoding="utf-8")
    manifest_diagnostic = ProjectDiagnostic(
        "provider-option-invalid",
        "error",
        "The provider option is invalid.",
        source=SourceLocation(PurePosixPath("view.toml"), 1, 1),
    )
    provider.inspection = replace(
        inspection(),
        diagnostics=(manifest_diagnostic,),
    )

    accepted = installed.inspect(inspection_request(project))
    assert [document.path for document in accepted.editor_documents] == [
        PurePosixPath("index.html")
    ]
    staging = tmp_path / "staging"
    staging.mkdir()
    staging.joinpath("index.html").write_text("<main></main>", encoding="utf-8")
    provider.report = BuildResult(PurePosixPath("index.html"), (manifest_diagnostic,))
    assert installed.build(
        provider_build_request(
            project,
            accepted,
            staging,
            cache_root=tmp_path / "cache" / ".artifacts" / ".cache",
        )
    ).diagnostics == (manifest_diagnostic,)

    provider.inspection = replace(
        inspection(),
        diagnostics=(
            replace(
                manifest_diagnostic,
                source=SourceLocation(PurePosixPath("private.toml"), 1, 1),
            ),
        ),
    )
    with pytest.raises(ConfigurationError, match=r"source path.*absent"):
        installed.inspect(inspection_request(project))


def test_provider_must_include_the_core_manifest_in_build_inputs(
    tmp_path: Path,
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.inspection = replace(
        inspection(),
        input_scope=(ProjectInput(PurePosixPath("index.html"), "file"),),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match=r"include.*view.toml.*input scope"):
        installed.inspect(inspection_request(project))


@pytest.mark.parametrize(
    ("kind", "target"),
    (
        ("cell", "report.total"),
        ("cell", "_"),
        ("value", "report..total"),
        ("value", "report.__dict__"),
        ("output", f"items[{1 << 53}]"),
        ("value", chr(0xD800)),
        ("value", "report" + ".item" * 65),
    ),
)
def test_provider_mount_targets_use_the_runtime_selector_grammar(
    tmp_path: Path,
    kind: str,
    target: str,
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.inspection = replace(
        inspection(),
        mounts=(
            MountDeclaration(
                "site:value:test",
                cast(Any, kind),
                SourceLocation(PurePosixPath("index.html"), 1, 1),
                (target,),
            ),
        ),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(
        ConfigurationError,
        match=r"target|reference|selection|private|safe integers|surrogate",
    ):
        installed.inspect(inspection_request(project))


def test_provider_mount_accepts_nested_value_targets(tmp_path: Path) -> None:
    provider = ProviderStub("example/html", "html")
    target = 'report.rows[0]["market.value"].total'
    provider.inspection = replace(
        inspection(),
        mounts=(
            MountDeclaration(
                "site:value:test",
                "value",
                SourceLocation(PurePosixPath("index.html"), 1, 1),
                (target,),
            ),
        ),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    assert installed.inspect(inspection_request(project)).mounts[0].allowed_targets == (
        target,
    )


def test_provider_mount_accepts_native_cell_names_and_configured_aliases(
    tmp_path: Path,
) -> None:
    provider = ProviderStub("example/html", "html")
    targets = ("_summary", "résumé", "report-name")
    provider.inspection = replace(
        inspection(),
        mounts=(
            MountDeclaration(
                "site:cell:test",
                "cell",
                SourceLocation(PurePosixPath("index.html"), 1, 1),
                targets,
            ),
        ),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    assert installed.inspect(inspection_request(project)).mounts[0].allowed_targets == (
        targets
    )


@pytest.mark.parametrize(
    "input_scope",
    (
        (
            ProjectInput(PurePosixPath("index.html"), "file"),
            ProjectInput(PurePosixPath("view.toml"), "file"),
            ProjectInput(PurePosixPath("VIEW.TOML"), "file"),
        ),
        (
            ProjectInput(PurePosixPath("index.html"), "file"),
            ProjectInput(PurePosixPath("view.toml"), "file"),
            ProjectInput(PurePosixPath("SRC"), "directory"),
            ProjectInput(PurePosixPath("src/App.tsx"), "file"),
        ),
    ),
)
def test_provider_input_scope_is_cross_platform_unambiguous(
    tmp_path: Path,
    input_scope: tuple[ProjectInput, ...],
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.inspection = replace(inspection(), input_scope=input_scope)
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match=r"case-colliding|overlapping"):
        installed.inspect(inspection_request(project))


@pytest.mark.parametrize("case", ("editor-case-collision", "unsafe-coordinate"))
def test_provider_inspection_rejects_cross_runtime_records(
    tmp_path: Path,
    case: str,
) -> None:
    provider = ProviderStub("example/html", "html")
    if case == "editor-case-collision":
        provider.inspection = replace(
            inspection(),
            editor_documents=(
                SourceDocument(PurePosixPath("src/App.tsx"), "tsx", "edit"),
                SourceDocument(PurePosixPath("src/app.tsx"), "tsx", "edit"),
            ),
            input_scope=(
                ProjectInput(PurePosixPath("src"), "directory"),
                ProjectInput(PurePosixPath("view.toml"), "file"),
            ),
        )
    else:
        provider.inspection = replace(
            inspection(),
            mounts=(
                MountDeclaration(
                    "site:cell:test",
                    "cell",
                    SourceLocation(PurePosixPath("index.html"), 1 << 53, 1),
                    ("overview",),
                ),
            ),
        )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match=r"case-colliding|browser-safe"):
        installed.inspect(inspection_request(project))


@pytest.mark.parametrize(
    "field",
    ("editor_documents", "input_scope", "mounts", "diagnostics"),
)
def test_provider_inspection_collections_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    provider = ProviderStub("example/html", "html")
    selected = inspection()
    limit = {
        "editor_documents": "_MAX_DOCUMENTS",
        "input_scope": "_MAX_INPUT_SCOPE",
        "mounts": "_MAX_MOUNTS",
        "diagnostics": "_MAX_DIAGNOSTICS",
    }[field]
    monkeypatch.setattr(conformance_module, limit, 1)
    if field == "editor_documents":
        selected = replace(
            selected,
            editor_documents=tuple(
                SourceDocument(PurePosixPath(f"source-{index}.html"), "html", "edit")
                for index in range(2)
            ),
        )
    elif field == "input_scope":
        selected = replace(
            selected,
            input_scope=tuple(
                ProjectInput(PurePosixPath(f"source-{index}.html"), "file")
                for index in range(2)
            ),
        )
    elif field == "mounts":
        selected = replace(
            selected,
            mounts=tuple(
                MountDeclaration(
                    f"site:value:{index}",
                    "value",
                    SourceLocation(PurePosixPath("index.html"), 1, 1),
                    ("report",),
                )
                for index in range(2)
            ),
        )
    else:
        selected = replace(
            selected,
            diagnostics=tuple(
                ProjectDiagnostic(
                    "provider-error",
                    "error",
                    "Invalid provider record.",
                )
                for _index in range(2)
            ),
        )
    provider.inspection = selected
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match="limits"):
        installed.inspect(inspection_request(project))


@pytest.mark.parametrize(
    "case",
    ("entries", "depth", "text", "nodes"),
)
def test_provider_options_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    provider = ProviderStub("example/html", "html")
    registry = ProviderRegistry((candidate("html", provider),))
    limit, options = {
        "entries": ("_MAX_OPTIONS", {"first": 1, "second": 2}),
        "depth": ("_MAX_JSON_DEPTH", {"nested": [[0]]}),
        "text": ("_MAX_TEXT_BYTES", {"text": "xx"}),
        "nodes": ("_MAX_JSON_NODES", {"items": [0]}),
    }[case]
    key = registry.ids[0]
    monkeypatch.setattr(conformance_module, limit, 1)

    with pytest.raises(ConfigurationError, match=r"limits|bounded|entries"):
        registry.validate_project(
            ViewProject(
                "dashboard",
                Path("view"),
                Path("view/view.toml"),
                key,
                cast(Any, options),
            )
        )


def test_provider_options_share_one_encoded_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example/html", "html")
    registry = ProviderRegistry((candidate("html", provider),))
    key = registry.ids[0]
    monkeypatch.setattr(conformance_module, "_MAX_JSON_BYTES", 20)

    with pytest.raises(ConfigurationError, match="encoded bytes"):
        registry.validate_project(
            ViewProject(
                "dashboard",
                Path("view"),
                Path("view/view.toml"),
                key,
                {"first": "aa", "second": "bb"},
            )
        )


def test_provider_mounts_share_one_encoded_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.inspection = replace(
        inspection(),
        mounts=tuple(
            MountDeclaration(
                f"site:value:{index}",
                "value",
                SourceLocation(PurePosixPath("index.html"), 1, 1),
                ("report",),
            )
            for index in range(2)
        ),
    )
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    monkeypatch.setattr(conformance_module, "_MAX_MOUNT_BYTES", 150)
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    with pytest.raises(ConfigurationError, match=r"projection sites.*encoded bytes"):
        installed.inspect(inspection_request(project))


@pytest.mark.parametrize(
    ("budget", "files", "message"),
    (
        (
            FileBudget(1, 10, 10),
            {
                PurePosixPath("index.html"): b"a",
                PurePosixPath("app.js"): b"b",
            },
            "contains 2 files",
        ),
        (
            FileBudget(10, 1, 10),
            {PurePosixPath("index.html"): b"ab"},
            "per-file limit",
        ),
        (
            FileBudget(10, 10, 2),
            {
                PurePosixPath("index.html"): b"ab",
                PurePosixPath("app.js"): b"c",
            },
            "more than 2 bytes",
        ),
    ),
)
def test_provider_starter_files_respect_the_project_input_budget(
    monkeypatch: pytest.MonkeyPatch,
    budget: FileBudget,
    files: dict[PurePosixPath, bytes],
    message: str,
) -> None:
    provider = ProviderStub("example/html", "html")
    provider.plan = files
    monkeypatch.setattr(conformance_module, "PROJECT_INPUT_BUDGET", budget)
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])

    with pytest.raises(ConfigurationError, match=message):
        installed.create(provider.starter, StarterContext("dashboard", "notebook"))


def test_registered_provider_rejects_manifest_case_collisions(tmp_path: Path) -> None:
    provider = ProviderStub("example/html", "html")
    registry = ProviderRegistry((candidate("html", provider),))
    installed = registry.get(registry.ids[0])
    project = ViewProject(
        "dashboard",
        tmp_path,
        tmp_path / "view.toml",
        installed.key,
        {},
    )

    provider.plan = {
        PurePosixPath("index.html"): b"<!doctype html>",
        PurePosixPath("VIEW.TOML"): b"provider = 'other/provider'",
    }
    with pytest.raises(ConfigurationError, match=r"reserves top-level 'view[.]toml'"):
        installed.create(provider.starter, StarterContext("dashboard", "notebook"))

    provider.inspection = replace(
        inspection(),
        editor_documents=(SourceDocument(PurePosixPath("VIEW.TOML"), "toml", "edit"),),
    )
    with pytest.raises(
        ConfigurationError, match=r"cannot expose Studio-owned 'view[.]toml'"
    ):
        installed.inspect(inspection_request(project))
