from __future__ import annotations

import hashlib
import shutil
from collections.abc import MutableMapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, cast

import pytest

from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._filesystem import tree as filesystem_tree
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.development import source_changes
from marimo_studio._server.development.source_changes import (
    SourceChange,
    SourceChangeProducer,
)
from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import InspectionRequest, ProjectInput
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import configured
from ..source_change_test_support import counting_registry as _counting_registry


def _watch_only_registry(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    watch_root: PurePosixPath,
) -> Any:
    registered = provider_registry().get(provider_id)

    class Provider:
        inspections = 0

        def inspect(self, request: InspectionRequest) -> object:
            self.inspections += 1
            inspection = registered.inspect(request)
            return replace(
                inspection,
                editor_documents=(),
                input_scope=(ProjectInput(watch_root, "directory"),),
                mounts=(),
            )

        def provenance(self, inspection: Any) -> Any:
            return registered.provenance(inspection)

    provider = Provider()
    registry = SimpleNamespace(
        get=lambda _selected: provider,
        validate_project=lambda project: project,
    )
    monkeypatch.setattr(source_changes, "provider_registry", lambda: registry)
    return provider


def test_catalog_reuses_unchanged_inspection_and_detects_direct_edits(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    provider = _counting_registry(monkeypatch, project.provider)

    producer = SourceChangeProducer(studio, project.name)
    for _ in range(2):
        assert producer.poll() is None

    assert provider.inspections == 1
    assert producer.catalog_current()

    source = project.root / "index.html"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert not producer.catalog_current()
    change = producer.poll()
    assert change is not None
    assert change.files[0]["path"] == "index.html"
    assert cast(str, change.files[0]["revision"]).startswith("sha256:")
    assert producer.catalog_current()
    assert provider.inspections == 2


def test_source_monitor_surfaces_provider_process_cleanup_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)

    class Provider:
        def inspect(self, _request: object) -> object:
            try:
                raise ProcessCleanupError("source monitor process survived")
            except ProcessCleanupError as cleanup:
                raise RuntimeError("provider inspection failed") from cleanup

    registry = SimpleNamespace(
        get=lambda _selected: Provider(),
        validate_project=lambda project: project,
    )
    monkeypatch.setattr(source_changes, "provider_registry", lambda: registry)

    with pytest.raises(
        ProcessCleanupError,
        match="source monitor process survived",
    ):
        SourceChangeProducer(studio, "dashboard")


def test_catalog_walks_the_provider_input_scope_once_per_change(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    _watch_only_registry(monkeypatch, project.provider, PurePosixPath("."))
    walks = 0
    walk_tree_entries = filesystem_tree._walk_tree_entries

    def count_walks(*args: Any, **kwargs: Any):
        nonlocal walks
        walks += 1
        yield from walk_tree_entries(*args, **kwargs)

    monkeypatch.setattr(filesystem_tree, "_walk_tree_entries", count_walks)
    producer = SourceChangeProducer(studio, project.name)

    assert walks == 1

    source = project.root / "index.html"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert producer.poll() is not None
    assert walks == 2


def test_catalog_probe_detects_a_file_added_to_an_existing_empty_directory(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    empty = project.root / "empty"
    empty.mkdir()
    _watch_only_registry(monkeypatch, project.provider, PurePosixPath("."))
    producer = SourceChangeProducer(studio, project.name)

    (empty / "new.txt").write_text("new", encoding="utf-8")

    assert not producer.catalog_current()


def test_watched_file_addition_and_removal_each_reinspect_once(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    provider = _watch_only_registry(
        monkeypatch,
        project.provider,
        PurePosixPath("."),
    )
    producer = SourceChangeProducer(studio, project.name)
    added = project.root / "interaction.js"

    added.write_text("export const active = true;\n", encoding="utf-8")
    created = producer.poll()
    added.unlink()
    removed = producer.poll()

    assert created is not None
    assert created.kind == "project"
    assert created.files == ()
    assert removed == SourceChange(kind="project", files=())
    assert provider.inspections == 3


def test_watch_plan_stays_bounded_by_declared_roots(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    for index in range(len(studio.views) + 5):
        (project.root / f"source-{index}.txt").write_text(
            str(index),
            encoding="utf-8",
        )
    _watch_only_registry(monkeypatch, project.provider, PurePosixPath("."))

    plan = SourceChangeProducer(studio, project.name).watch_plan

    assert plan.roots == (project.root.absolute(),)
    assert plan.excluded == (artifact_root(project).absolute(),)
    assert len(plan.files) <= len(studio.views) + 4
    assert all("source-" not in path.name for path in plan.files)


def test_source_scan_counts_directories_toward_its_entry_limit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    watched = project.root / "watched"
    watched.mkdir()
    _watch_only_registry(monkeypatch, project.provider, PurePosixPath("watched"))
    producer = SourceChangeProducer(studio, project.name)
    for index in range(3):
        (watched / f"empty-{index}").mkdir()
    budget = SimpleNamespace(
        max_file_bytes=source_changes.PROJECT_INPUT_BUDGET.max_file_bytes,
        max_files=3,
    )
    monkeypatch.setattr(source_changes, "PROJECT_INPUT_BUDGET", budget)

    with pytest.raises(ConfigurationError, match="more than 3 entries"):
        producer.poll()


def test_source_scan_stops_when_its_owner_is_cancelled_mid_scan(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    watched = project.root / "watched"
    watched.mkdir()
    _watch_only_registry(monkeypatch, project.provider, PurePosixPath("watched"))
    producer = SourceChangeProducer(studio, project.name)
    for index in range(5):
        (watched / f"source-{index}.txt").write_text("source", encoding="utf-8")

    class Cancellation:
        checks = 0

        @property
        def cancelled(self) -> bool:
            self.checks += 1
            return self.checks >= 4

    cancellation = Cancellation()
    monkeypatch.setattr(
        source_changes,
        "current_provider_cancellation",
        lambda: cancellation,
    )

    with pytest.raises(ConfigurationError, match="scan was cancelled"):
        producer.poll()


def test_windows_stamp_hashes_a_bounded_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"first")

    def reject_read_bytes(_path: Path) -> bytes:
        pytest.fail("Windows stamps must not allocate the complete file")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)

    assert (
        source_changes._path_stamp(source, content_hashing=True)
        == hashlib.sha256(b"first").hexdigest()
    )


def test_windows_stamp_uses_metadata_for_an_oversized_sparse_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "large.bin"
    size = source_changes.PROJECT_INPUT_BUDGET.max_file_bytes + 1
    with source.open("wb") as stream:
        stream.truncate(size)

    monkeypatch.setattr(
        source_changes,
        "digest_secure_file",
        lambda *_args, **_kwargs: pytest.fail("Oversized files must not be hashed"),
    )

    stamp = source_changes._path_stamp(source, content_hashing=True)

    assert isinstance(stamp, tuple)
    assert stamp[2] == size


def test_changed_file_details_ignore_unadvertised_watch_root_files(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    inspection = (
        provider_registry().get(project.provider).inspect(inspection_request(project))
    )
    opaque = project.root / "opaque.bin"
    with opaque.open("wb") as stream:
        stream.truncate(source_changes.PROJECT_INPUT_BUDGET.max_file_bytes + 1)
    monkeypatch.setattr(
        source_changes,
        "digest_secure_file",
        lambda *_args, **_kwargs: pytest.fail("Unadvertised files must not be hashed"),
    )

    assert (
        source_changes._changed_files(
            project,
            inspection,
            {("view", opaque)},
        )
        == []
    )


def test_changed_file_details_fall_back_to_full_reconciliation_when_one_is_unstable(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    inspection = (
        provider_registry().get(project.provider).inspect(inspection_request(project))
    )
    source = project.root / "index.html"
    stable = project.root / "app.css"
    digest = source_changes.digest_secure_file

    def fail_one_digest(root: Path, path: Path, label: str, *, max_bytes: int) -> str:
        if path == source:
            raise ConfigurationError("source changed during hashing")
        return digest(root, path, label, max_bytes=max_bytes)

    monkeypatch.setattr(
        source_changes,
        "digest_secure_file",
        fail_one_digest,
    )

    assert (
        source_changes._changed_files(
            project,
            inspection,
            {("view", stable), ("view", source)},
        )
        == []
    )


def test_view_manifest_addition_and_removal_reload_workspace_discovery(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    provider = _counting_registry(monkeypatch, project.provider)
    producer = SourceChangeProducer(studio, project.name)
    added = studio.view_root / "comparison"

    shutil.copytree(studio.views["executive"].root, added)
    created = producer.poll()
    assert "comparison" in producer.studio.views
    shutil.rmtree(added)
    removed = producer.poll()

    assert created == SourceChange(kind="views", files=())
    assert removed == SourceChange(kind="views", files=())
    assert "comparison" not in producer.studio.views
    assert provider.inspections == 1


def test_selected_manifest_change_reloads_provider_options(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    provider = _counting_registry(monkeypatch, project.provider)
    producer = SourceChangeProducer(studio, project.name)
    replacement = project.root / "alternate.html"
    replacement.write_text(
        (project.root / "index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    project.manifest.write_text(
        project.manifest.read_text(encoding="utf-8")
        + '\n[options]\nentrypoint = "alternate.html"\n',
        encoding="utf-8",
    )

    inventory = producer.poll()
    project_change = producer.poll()

    assert inventory == SourceChange(kind="views", files=())
    assert project_change == SourceChange(kind="project", files=())
    assert producer.studio.views["dashboard"].options["entrypoint"] == (
        "alternate.html"
    )
    assert provider.inspections == 2


def test_config_change_refreshes_inventory_then_selected_project(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    producer = SourceChangeProducer(studio, "dashboard")

    def update(config: MutableMapping[str, object]) -> None:
        config["show_cell_logs"] = False

    update_notebook_config(studio.notebook, update)

    assert producer.poll() == SourceChange("views", ())
    assert producer.poll() == SourceChange("project", ())


def test_selected_manifest_missing_and_recovery_each_refresh_project(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)
    producer = SourceChangeProducer(studio, "dashboard")
    manifest = studio.views["dashboard"].manifest
    source = manifest.read_text(encoding="utf-8")

    manifest.unlink()

    assert producer.poll() == SourceChange("views", ())
    assert producer.poll() == SourceChange("project", ())
    assert producer.poll() is None

    manifest.write_text(source, encoding="utf-8")

    assert producer.poll() == SourceChange("views", ())
    assert producer.poll() == SourceChange("project", ())


def test_sibling_manifest_change_is_inventory_only(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    provider = _counting_registry(monkeypatch, project.provider)
    producer = SourceChangeProducer(studio, project.name)
    sibling = studio.views["executive"]
    sibling.manifest.write_text(
        sibling.manifest.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    inventory = producer.poll()

    assert inventory == SourceChange(kind="views", files=())
    assert producer.poll() is None
    assert provider.inspections == 1


def test_inspection_failure_keeps_a_repair_watch(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    registered = provider_registry().get(project.provider)
    source = project.root / "index.html"
    original = source.read_text(encoding="utf-8")
    source.write_text("broken", encoding="utf-8")
    inspections = 0

    class Provider:
        def inspect(self, selected: object) -> object:
            nonlocal inspections
            inspections += 1
            if source.read_text(encoding="utf-8") == "broken":
                raise ValueError("source is temporarily invalid")
            return registered.inspect(cast(Any, selected))

        def provenance(self, inspection: Any) -> Any:
            return registered.provenance(inspection)

    registry = SimpleNamespace(
        get=lambda _selected: Provider(),
        validate_project=lambda project: project,
    )
    monkeypatch.setattr(source_changes, "provider_registry", lambda: registry)
    producer = SourceChangeProducer(studio, project.name)
    cache_probe = artifact_root(project) / ".cache" / "watch-probe"
    cache_probe.parent.mkdir(parents=True, exist_ok=True)
    cache_probe.write_text("cache", encoding="utf-8")

    assert producer.poll() is None
    assert inspections == 1

    source.write_text(original, encoding="utf-8")
    repaired = producer.poll()

    assert repaired is not None
    assert repaired.kind == "project"
    assert inspections == 2


def test_failed_reinspection_invalidates_the_previous_catalog(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = configured(notebook_path)
    project = studio.views["dashboard"]
    registered = provider_registry().get(project.provider)
    source = project.root / "index.html"
    fail = False

    class Provider:
        def inspect(self, selected: object) -> object:
            if fail:
                raise ValueError("source is temporarily invalid")
            return registered.inspect(cast(Any, selected))

        def provenance(self, inspection: Any) -> Any:
            return registered.provenance(inspection)

    registry = SimpleNamespace(
        get=lambda _selected: Provider(),
        validate_project=lambda project: project,
    )
    monkeypatch.setattr(source_changes, "provider_registry", lambda: registry)
    producer = SourceChangeProducer(studio, project.name)
    assert producer.catalog()[1].editor_documents

    fail = True
    source.write_text(
        source.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert producer.poll() is not None
    with pytest.raises(ConfigurationError, match="inspection is unavailable"):
        producer.catalog()

    fail = False
    source.write_text(
        source.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert producer.poll() is not None
    assert producer.catalog()[1].editor_documents
