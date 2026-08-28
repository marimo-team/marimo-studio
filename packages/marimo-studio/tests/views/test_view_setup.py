from __future__ import annotations

import multiprocessing
import re
import shutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import marimo
import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._views.create as create_module
import marimo_studio._workspace.transactions as workspace_transactions
from marimo_studio._views.api import prepare_view
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._views.remove import delete_view
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import canonical_view_root, load_studio_definition
from marimo_studio._workspace.metadata import (
    read_notebook_metadata,
)
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio.errors import ConfigurationError, NotebookSourceError
from marimo_studio.errors._internal import WorkspaceInitializationError
from marimo_studio.view_providers._bundled.vanilla import provider as vanilla_provider

from ..helpers import empty_notebook_source
from .workspace_test_support import (
    _create_view_in_process,
    _reject_manifestless_view_in_process,
)


def test_view_setup_configures_the_notebook_and_creates_each_view(
    notebook_path: Path,
) -> None:
    original = notebook_path.read_text(encoding="utf-8")

    result = prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    document = read_notebook_metadata(notebook_path)
    document_source = result.root.joinpath("index.html").read_text(encoding="utf-8")

    assert result.workspace == studio
    assert studio.uses_notebook_config
    assert studio.config_path == notebook_path
    assert studio.view_root == (
        notebook_path.parent / "__marimo__" / "studio" / notebook_path.stem
    )
    assert document is not None
    assert document["tool"]["marimo-studio"]["default"] == "dashboard"
    assert "marimo-studio" in document["dependencies"]
    assert notebook_path.read_text(encoding="utf-8").endswith(original)
    assert re.search(r"<h1[^>]*>\s*Dashboard\s*</h1>", document_source)
    assert document["tool"]["marimo-studio"].get("cells", {}) == {}
    assert resolve_studio(studio).aliases == {}
    dashboard = studio.views["dashboard"].root / "index.html"
    dashboard.write_text(
        dashboard.read_text(encoding="utf-8").replace(
            "</style>", ".custom {}\n</style>"
        ),
        encoding="utf-8",
    )

    prepare_view(notebook_path, "report")

    assert ".custom {}" in dashboard.read_text(encoding="utf-8")
    report = load_studio(notebook_path).views["report"].root
    assert set(
        studio.view_root.joinpath(".gitignore").read_text(encoding="utf-8").splitlines()
    ) == {"/.locks/", "*/.artifacts/"}
    assert report.joinpath("index.html").is_file()
    assert not report.joinpath(".artifacts").exists()


def test_repeated_and_dry_run_setup_report_file_changes(
    notebook_path: Path,
) -> None:
    created = prepare_view(notebook_path)
    repeated = prepare_view(notebook_path)
    preview = prepare_view(notebook_path, dry_run=True)

    payload = created.to_dict()
    assert payload["schema"] == 1
    assert repeated.created == ()
    assert repeated.updated == ()
    assert preview.created == ()
    assert preview.updated == ()


def test_concurrent_view_setup_serializes_the_same_view_name(
    notebook_path: Path,
) -> None:
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=2)
        return prepare_view(notebook_path, "dashboard")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: create(), range(2)))

    assert all(result.workspace is not None for result in results)
    assert sum(bool(result.created) for result in results) == 1
    assert {result.provider for result in results} == {"marimo-studio/vanilla"}
    studio = load_studio(notebook_path)
    assert tuple(studio.views) == ("dashboard",)


def test_concurrent_first_view_threads_create_one_coherent_catalog(
    notebook_path: Path,
) -> None:
    start = Barrier(2)

    def create(name: str) -> str:
        start.wait()
        return prepare_view(notebook_path, name).name

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(create, "dashboard"),
                executor.submit(create, "executive"),
            )
        )

    studio = load_studio(notebook_path)
    assert set(results) == {"dashboard", "executive"}
    assert set(studio.views) == {"dashboard", "executive"}
    assert studio.default_view in studio.views


def test_catalog_race_does_not_run_provider_creation_under_mutation_locks(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyproject = notebook_path.parent / "pyproject.toml"
    pyproject.write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )
    create = vanilla_provider.create
    calls = 0

    def change_catalog_after_planning(starter, context):
        nonlocal calls
        plan = create(starter, context)
        calls += 1
        if calls == 2:
            pyproject.write_text(
                pyproject.read_text(encoding="utf-8").replace(
                    'default = "dashboard"',
                    'default = "operations"',
                ),
                encoding="utf-8",
            )
        return plan

    monkeypatch.setattr(vanilla_provider, "create", change_catalog_after_planning)

    with pytest.raises(ConfigurationError, match="catalog changed"):
        prepare_view(notebook_path, "report")

    assert calls == 2
    assert not tuple(canonical_view_root(notebook_path).glob("*/view.toml"))


def test_existing_view_inspection_runs_outside_mutation_locks(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    held = 0
    inspections = 0
    workspace_lock = create_module.workspace_catalog_lock
    view_lock = create_module.view_mutation_lock
    inspect = create_module.inspect_view_project_sync

    @contextmanager
    def observed_workspace_lock(view_root: Path):
        nonlocal held
        with workspace_lock(view_root):
            held += 1
            try:
                yield
            finally:
                held -= 1

    @contextmanager
    def observed_view_lock(view_root: Path, view_name: str):
        nonlocal held
        with view_lock(view_root, view_name):
            held += 1
            try:
                yield
            finally:
                held -= 1

    def observed_inspection(project):
        nonlocal inspections
        assert held == 0
        inspections += 1
        return inspect(project)

    monkeypatch.setattr(
        create_module, "workspace_catalog_lock", observed_workspace_lock
    )
    monkeypatch.setattr(create_module, "view_mutation_lock", observed_view_lock)
    monkeypatch.setattr(
        create_module,
        "inspect_view_project_sync",
        observed_inspection,
    )

    prepare_view(notebook_path)

    assert inspections == 1


@pytest.mark.native_process
def test_spawned_setup_rejects_a_manifestless_view_without_mutation(
    notebook_path: Path,
) -> None:
    original = notebook_path.read_bytes()
    view_root = canonical_view_root(notebook_path)
    occupied = view_root / "dashboard"
    occupied.mkdir(parents=True)
    sentinel = occupied / "sentinel.bin"
    content = b"\x00preserve-manifestless-view\xff"
    sentinel.write_bytes(content)
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        results = tuple(
            executor.map(
                _reject_manifestless_view_in_process,
                (str(notebook_path), str(notebook_path)),
                ("dashboard", "dashboard"),
            )
        )

    assert all("required view.toml" in result for result in results)
    assert notebook_path.read_bytes() == original
    assert sentinel.read_bytes() == content
    assert tuple(path.name for path in occupied.iterdir()) == ("sentinel.bin",)
    assert not (view_root / ".locks").exists()


@pytest.mark.native_process
def test_spawned_first_view_processes_create_one_coherent_catalog(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    signals = tmp_path / "create-signals"
    signals.mkdir()
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(
                    _create_view_in_process,
                    str(notebook_path),
                    "dashboard",
                    str(signals),
                    2,
                ),
                executor.submit(
                    _create_view_in_process,
                    str(notebook_path),
                    "executive",
                    str(signals),
                    2,
                ),
            )
        )

    studio = load_studio(notebook_path)
    assert set(results) == {"dashboard", "executive"}
    assert set(studio.views) == {"dashboard", "executive"}
    assert studio.default_view in studio.views


def test_definition_materializes_only_after_a_view_exists(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
    shutil.rmtree(
        setup.workspace.view_root if setup.workspace is not None else setup.root
    )

    definition = load_studio_definition(notebook_path)

    assert isinstance(definition, StudioDefinition)
    assert not isinstance(definition, StudioWorkspace)
    assert definition.default_view == "dashboard"
    with pytest.raises(WorkspaceInitializationError, match="first view"):
        load_studio(notebook_path)

    initialized = prepare_view(notebook_path).workspace

    assert isinstance(initialized, StudioWorkspace)
    assert list(initialized.views) == ["dashboard"]


def test_view_discovery_rejects_a_symlinked_view_directory(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
    external = tmp_path / "external-view"
    setup.root.rename(external)
    setup.root.symlink_to(external, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="symlink"):
        load_studio(notebook_path)


def test_new_view_exposes_page_and_starter_instructions_without_mounts(
    notebook_path: Path,
) -> None:
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8").replace(
            "@app.cell\ndef _():",
            "@app.cell\ndef setup():",
            1,
        ),
        encoding="utf-8",
    )

    result = prepare_view(notebook_path)
    inspection = inspect_view_project_sync(load_studio(notebook_path).view(result.name))
    document = read_notebook_metadata(notebook_path)

    assert [
        (item.path.as_posix(), item.language, item.access)
        for item in inspection.editor_documents
    ] == [
        ("index.html", "html", "edit"),
        ("AGENTS.md", "markdown", "edit"),
    ]
    assert inspection.mounts == ()
    assert document is not None
    assert document["tool"]["marimo-studio"].get("cells", {}) == {}


def test_zero_cell_notebook_rejects_non_notebook_source(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        empty_notebook_source().replace(
            "\n\nif __name__",
            "\nvalue = 1\n\nif __name__",
        ),
        encoding="utf-8",
    )
    with pytest.raises(NotebookSourceError):
        prepare_view(notebook)


def test_setup_preserves_crlf_preamble_and_notebook_body(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    source = (
        "#!/usr/bin/env python\r\n"
        "# -*- coding: utf-8 -*-\r\n"
        f'import marimo\r\n__generated_with = "{marimo.__version__}"\r\n'
        "app = marimo.App()\r\n"
        "@app.cell\r\n"
        "def _():\r\n"
        "    return\r\n"
    )
    notebook.write_bytes(source.encode())

    prepare_view(notebook)

    updated = notebook.read_bytes()
    assert updated.startswith(
        b"#!/usr/bin/env python\r\n# -*- coding: utf-8 -*-\r\n# /// script\r\n"
    )
    assert updated.endswith(source.split("# -*- coding: utf-8 -*-\r\n", 1)[1].encode())
    assert b"\n" not in updated.replace(b"\r\n", b"")


def test_repeated_setup_preserves_crlf_metadata(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    source = (
        "# /// script\r\n"
        '# requires-python = ">=3.10"\r\n'
        '# dependencies = ["marimo-studio"]\r\n'
        "# ///\r\n"
        "\r\n"
        f'import marimo\r\n__generated_with = "{marimo.__version__}"\r\n'
        "app = marimo.App()\r\n"
        "@app.cell\r\n"
        "def _():\r\n"
        "    return\r\n"
    )
    notebook.write_bytes(source.encode())

    prepare_view(notebook, "dashboard")
    prepare_view(notebook, "report")

    updated = notebook.read_bytes()
    assert b"\r\r\n" not in updated
    assert b"\n" not in updated.replace(b"\r\n", b"")
    assert read_notebook_metadata(notebook) is not None


def test_setup_rolls_back_notebook_and_view_files_after_write_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = notebook_path.read_bytes()
    write = workspace_transactions.atomic_write_bytes
    calls = 0

    def fail_second_write(
        path: Path,
        content: bytes,
        *,
        root: Path | None = None,
        filesystem: secure_files.SecureDirectory | None = None,
        mode: int | None = None,
    ) -> secure_files.FileIdentity:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated write failure")
        return write(
            path,
            content,
            root=root,
            filesystem=filesystem,
            mode=mode,
        )

    monkeypatch.setattr(
        workspace_transactions,
        "atomic_write_bytes",
        fail_second_write,
    )

    with pytest.raises(OSError, match="simulated write failure"):
        prepare_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert not (canonical_view_root(notebook_path) / "dashboard").exists()


@pytest.mark.parametrize("name", ["notes.txt", "script.py"])
def test_setup_rejects_non_notebooks_without_mutation(
    tmp_path: Path,
    name: str,
) -> None:
    target = tmp_path / name
    target.write_text("answer = 42\n", encoding="utf-8")
    original = target.read_bytes()

    with pytest.raises(ConfigurationError):
        prepare_view(target)

    assert target.read_bytes() == original
    assert not (tmp_path / "__marimo__").exists()


def test_project_configuration_uses_the_notebook_local_view_directory(
    notebook_path: Path,
) -> None:
    project_root = notebook_path.parent
    notebook_dir = project_root / "notebooks"
    notebook_dir.mkdir()
    notebook = notebook_dir / notebook_path.name
    notebook.write_bytes(notebook_path.read_bytes())
    original = notebook.read_bytes()
    pyproject = project_root / "pyproject.toml"
    pyproject.write_text(
        f"""\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["marimo-studio==1.2.3"]

[tool.marimo-studio]
notebook = "notebooks/{notebook.name}"
default = "executive"

[tool.marimo-studio.cells]
""",
        encoding="utf-8",
    )

    prepare_view(notebook)
    studio = load_studio(notebook)

    assert studio.config_source == "pyproject"
    assert studio.config_path == pyproject
    assert studio.default_view == "executive"
    assert set(studio.views) == {"executive"}
    assert studio.cells == {}
    assert resolve_studio(studio).aliases == {}
    assert studio.view_root == notebook_dir / "__marimo__" / "studio" / notebook.stem
    assert notebook.read_bytes() == original


def test_project_configuration_tracks_a_removed_default_view(
    notebook_path: Path,
) -> None:
    project_root = notebook_path.parent
    pyproject = project_root / "pyproject.toml"
    pyproject.write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")

    delete_view(load_studio(pyproject), "dashboard")

    updated = load_studio(pyproject)
    assert updated.default_view == "executive"
    assert list(updated.views) == ["executive"]
