"""Protect source document compare-and-swap transactions."""

import multiprocessing
import os
import stat
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._views.sources as sources_module
from marimo_studio._artifacts.inputs import (
    ProjectRevisionSnapshot,
    project_revision,
)
from marimo_studio._views.build import publish_view as publish_artifact
from marimo_studio._views.inspection import inspection_request
from marimo_studio._views.sources import (
    PreparedSourceWrite,
    read_project_source,
    read_source,
    source_spec,
    write_project_source,
    write_source,
)
from marimo_studio._workspace import load_studio
from marimo_studio.errors import SourceConflictError, ViewProjectError
from marimo_studio.view_providers import (
    InspectionRequest,
    ProjectInspection,
    ViewProject,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.records import ProviderProvenance

from .source_test_support import SOURCE_PATH
from .source_test_support import document as _document
from .source_test_support import studio as _studio


def _replace_in_process(
    notebook: str,
    content: str,
    revision: str,
) -> str:
    studio = load_studio(Path(notebook))
    try:
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            content,
            revision,
        )
    except SourceConflictError:
        return "conflict"
    return "written"


def test_source_compare_and_swap_allows_one_concurrent_writer(
    notebook_path: Path,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", SOURCE_PATH)
    start = Barrier(2)

    def replace_source(content: str) -> str:
        start.wait()
        try:
            write_source(
                studio,
                "dashboard",
                SOURCE_PATH,
                content,
                current.revision,
            )
        except SourceConflictError:
            return "conflict"
        return "written"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(replace_source, _document("red")),
            executor.submit(replace_source, _document("blue")),
        )
    assert sorted(future.result() for future in futures) == ["conflict", "written"]


def test_source_commit_preserves_an_external_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", SOURCE_PATH)
    path = studio.views["dashboard"].root / SOURCE_PATH
    external = _document("external edit")
    claim = secure_files.SecureDirectory.quarantine_if_identity
    edited = False

    def edit_then_claim(
        filesystem: secure_files.SecureDirectory,
        selected: Path,
        expected: secure_files.FileIdentity,
    ) -> Path:
        nonlocal edited
        if selected == path and not edited:
            edited = True
            path.write_text(external, encoding="utf-8")
        return claim(filesystem, selected, expected)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "quarantine_if_identity",
        edit_then_claim,
    )

    with pytest.raises(SourceConflictError):
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("browser edit"),
            current.revision,
        )

    assert edited
    assert path.read_text(encoding="utf-8") == external


def test_source_conflict_omits_revision_when_the_source_disappears(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", SOURCE_PATH)
    path = studio.views["dashboard"].root / SOURCE_PATH
    claim = secure_files.SecureDirectory.quarantine_if_identity
    removed = False

    def remove_then_claim(
        filesystem: secure_files.SecureDirectory,
        selected: Path,
        expected: secure_files.FileIdentity,
    ) -> Path:
        nonlocal removed
        if selected == path and not removed:
            removed = True
            path.unlink()
        return claim(filesystem, selected, expected)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "quarantine_if_identity",
        remove_then_claim,
    )

    with pytest.raises(SourceConflictError) as captured:
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("browser edit"),
            current.revision,
        )

    assert removed
    assert captured.value.revision is None
    assert "revision" not in captured.value.diagnostic_details()


@pytest.mark.skipif(os.name == "nt", reason="POSIX source modes are not portable")
def test_source_commit_preserves_the_file_mode(notebook_path: Path) -> None:
    studio = _studio(notebook_path)
    path = studio.views["dashboard"].root / SOURCE_PATH
    path.chmod(0o664)
    current = read_source(studio, "dashboard", SOURCE_PATH)

    write_source(
        studio,
        "dashboard",
        SOURCE_PATH,
        _document("browser edit"),
        current.revision,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o664


def test_source_commit_cleans_its_claim_after_identity_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    path = studio.views["dashboard"].root / SOURCE_PATH
    current = read_source(studio, "dashboard", SOURCE_PATH)
    replacement = _document("browser edit")
    identity = secure_files.SecureDirectory.file_identity
    failed = False

    def fail_committed_identity(
        filesystem: secure_files.SecureDirectory,
        selected: Path,
    ) -> secure_files.FileIdentity:
        nonlocal failed
        if selected == path and not failed:
            failed = True
            raise PermissionError("identity unavailable")
        return identity(filesystem, selected)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "file_identity",
        fail_committed_identity,
    )

    with pytest.raises(SourceConflictError) as error:
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            replacement,
            current.revision,
        )

    assert failed
    assert error.value.external_recovery is None
    assert path.read_text(encoding="utf-8") == replacement
    assert not tuple(path.parent.glob(f".{path.name}.rollback-*"))
    assert not tuple(path.parent.glob(f".{path.name}.*.cas"))


def test_source_conflict_reports_a_preserved_claim(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    path = studio.views["dashboard"].root / SOURCE_PATH
    current = read_source(studio, "dashboard", SOURCE_PATH)
    replacement = _document("browser edit")
    unlink = secure_files.SecureDirectory.unlink

    def preserve_claim(
        filesystem: secure_files.SecureDirectory,
        selected: Path,
    ) -> None:
        if selected.name.startswith(f".{path.name}.rollback-"):
            raise PermissionError("claim is still open")
        unlink(filesystem, selected)

    monkeypatch.setattr(secure_files.SecureDirectory, "unlink", preserve_claim)

    with pytest.raises(SourceConflictError) as captured:
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            replacement,
            current.revision,
        )

    recovery = captured.value.external_recovery
    assert recovery is not None
    recovery_path = Path(recovery)
    assert path.read_text(encoding="utf-8") == replacement
    assert recovery_path.read_text(encoding="utf-8") == current.content
    assert not tuple(path.parent.glob(f".{path.name}.*.cas"))


def test_source_save_is_not_blocked_by_a_provider_build(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    project = studio.view("dashboard")
    provider = provider_registry().get(project.provider)
    build = provider.build
    started = Event()
    release = Event()
    saved = Event()

    def slow_build(request):
        started.set()
        assert release.wait(timeout=2)
        return build(request)

    monkeypatch.setattr(provider, "build", slow_build)
    current = read_source(studio, "dashboard", SOURCE_PATH)

    def save_source():
        result = write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("blue"),
            current.revision,
        )
        saved.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        building = executor.submit(publish_artifact, project, "development")
        assert started.wait(timeout=2)
        saving = executor.submit(save_source)
        try:
            assert saved.wait(timeout=2)
            assert not building.done()
            assert saving.result(timeout=2).content == _document("blue")
        finally:
            release.set()
        with pytest.raises(ViewProjectError, match="changed while"):
            building.result(timeout=2)


@pytest.mark.native_process
def test_source_compare_and_swap_allows_one_cross_process_writer(
    notebook_path: Path,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", SOURCE_PATH)
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
        futures = (
            executor.submit(
                _replace_in_process,
                str(notebook_path),
                _document("red"),
                current.revision,
            ),
            executor.submit(
                _replace_in_process,
                str(notebook_path),
                _document("blue"),
                current.revision,
            ),
        )

    assert sorted(future.result() for future in futures) == ["conflict", "written"]


def test_source_write_revalidates_catalog_identity_after_waiting_for_view_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    project = studio.views["dashboard"]
    provider = provider_registry().get(project.provider)
    inspect = provider.inspect
    path = SOURCE_PATH
    access_marker = "# source-access = read"
    inspection_calls = 0

    def inspect_with_manifest_access(
        request: InspectionRequest,
    ) -> ProjectInspection:
        nonlocal inspection_calls
        inspection_calls += 1
        inspection = inspect(request)
        selected = request.project
        if access_marker not in selected.manifest.read_text(encoding="utf-8"):
            return inspection
        return replace(
            inspection,
            editor_documents=tuple(
                replace(item, access="read") if item.path.as_posix() == path else item
                for item in inspection.editor_documents
            ),
        )

    monkeypatch.setattr(provider, "inspect", inspect_with_manifest_access)
    inspection = provider.inspect(inspection_request(project))
    spec = source_spec(inspection, path, project.name)
    prepared = PreparedSourceWrite(
        project,
        inspection,
        project_revision(project, inspection, provider.provenance(inspection)),
        spec,
    )
    current = read_project_source(
        studio,
        project,
        spec,
    )
    original_lock = sources_module.view_mutation_lock
    waiting = Barrier(2)

    @contextmanager
    def observed_lock(view_root: Path, view_name: str) -> Iterator[None]:
        waiting.wait(timeout=5)
        with original_lock(view_root, view_name):
            yield

    monkeypatch.setattr(sources_module, "view_mutation_lock", observed_lock)
    intended = _document("intended")
    with ThreadPoolExecutor(max_workers=1) as executor:
        with original_lock(studio.view_root, project.name):
            pending = executor.submit(
                write_project_source,
                studio,
                prepared,
                intended,
                current.revision,
            )
            waiting.wait(timeout=5)
            project.manifest.write_text(
                f"{project.manifest.read_text(encoding='utf-8').rstrip()}\n"
                f"{access_marker}\n",
                encoding="utf-8",
            )
        with pytest.raises(SourceConflictError):
            pending.result(timeout=5)
    assert inspection_calls == 1
    assert (project.root / spec.path).read_text(encoding="utf-8") == current.content


def test_source_input_hashing_finishes_before_the_mutation_lock(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    project = studio.views["dashboard"]
    provider = provider_registry().get(project.provider)
    inspection = provider.inspect(inspection_request(project))
    spec = source_spec(inspection, SOURCE_PATH, project.name)
    prepared = PreparedSourceWrite(
        project,
        inspection,
        project_revision(project, inspection, provider.provenance(inspection)),
        spec,
    )
    current = read_project_source(studio, project, spec)
    inside_lock = False
    snapshot = sources_module.project_revision_snapshot
    mutation_lock = sources_module.view_mutation_lock

    def observed_snapshot(
        selected: ViewProject,
        selected_inspection: ProjectInspection,
        provenance: ProviderProvenance,
    ) -> ProjectRevisionSnapshot:
        assert not inside_lock
        return snapshot(selected, selected_inspection, provenance)

    @contextmanager
    def observed_lock(view_root: Path, view_name: str) -> Iterator[None]:
        nonlocal inside_lock
        with mutation_lock(view_root, view_name):
            inside_lock = True
            try:
                yield
            finally:
                inside_lock = False

    monkeypatch.setattr(sources_module, "project_revision_snapshot", observed_snapshot)
    monkeypatch.setattr(sources_module, "view_mutation_lock", observed_lock)

    written = write_project_source(
        studio,
        prepared,
        _document("updated"),
        current.revision,
    )

    assert "updated" in written.content
    assert (project.root / spec.path).read_text(encoding="utf-8") == written.content
