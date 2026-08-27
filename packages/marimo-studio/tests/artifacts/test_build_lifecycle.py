"""Exercise provider builds, cache hits, cancellation, and publication state."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Any

import pytest

import marimo_studio._artifacts.inputs as inputs_module
import marimo_studio._artifacts.publication as publication_module
import marimo_studio._artifacts.repository as repository_module
import marimo_studio._artifacts.retention as retention_module
import marimo_studio._views.build as build_module
from marimo_studio._artifacts.inputs import project_revision
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.repository import (
    read_artifact_state,
    read_build_state,
    read_published_artifact,
)
from marimo_studio._artifacts.retention import ArtifactLease, lease_published_artifact
from marimo_studio._processes.cancellation import provider_cancellation
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectDiagnostic,
    ProviderCancellation,
    ViewProject,
)
from marimo_studio.view_providers._host import provider_registry

from ..artifact_test_support import (
    change_document as _change_document,
)
from ..artifact_test_support import (
    profile_path as _profile_path,
)
from ..artifact_test_support import (
    project as _project,
)
from ..artifact_test_support import (
    publish_artifact,
)
from ..artifact_test_support import (
    read_json as _read_json,
)
from ..artifact_test_support import (
    write_json as _write_json,
)


def test_cache_hit_preserves_successful_build_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build
    calls = 0
    warning = ProjectDiagnostic(
        code="provider-build-warning",
        severity="warning",
        message="Provider retained a build warning.",
        hint="Review the generated page.",
    )

    def build_with_warning(request: BuildRequest) -> BuildResult:
        nonlocal calls
        calls += 1
        report = build(request)
        return replace(report, diagnostics=(warning,))

    monkeypatch.setattr(provider, "build", build_with_warning)
    first_lease = publish_artifact_lease(project, "development")
    first = first_lease.artifact
    first_lease.close()
    first_build = read_build_state(project, "development")
    receipt = _read_json(_profile_path(project))
    assert receipt["schema"] == 2
    assert receipt["published"]["diagnostics"] == [warning.to_dict()]
    assert receipt["published"]["duration_ms"] == first_build.duration_ms
    receipt["build"].update(
        phase="failed",
        diagnostics=[
            {
                "code": "later-build-failure",
                "severity": "error",
                "message": "A later attempt failed.",
                "hint": "Retry the build.",
                "source": None,
            }
        ],
        duration_ms=1,
    )
    _write_json(_profile_path(project), receipt)

    cached_lease = publish_artifact_lease(project, "development")
    cached = cached_lease.artifact
    cached_lease.close()
    cached_build = read_build_state(project, "development")

    assert calls == 1
    assert cached.artifact_revision == first.artifact_revision
    assert first_build.diagnostics == (warning,)
    assert first_build.duration_ms is not None
    assert cached_build == first_build
    assert cached_build.project_revision == cached.project_revision
    assert cached_build.artifact_revision == cached.artifact_revision


def test_build_content_hashing_finishes_before_the_mutation_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    inside_lock = False
    mutation_lock = build_module.view_mutation_lock
    capture_entry = inputs_module._capture_entry
    publication_files = publication_module.artifact_files
    repository_files = repository_module.artifact_files

    @contextmanager
    def observed_lock(view_root: Path, view_name: str) -> Iterator[None]:
        nonlocal inside_lock
        with mutation_lock(view_root, view_name):
            inside_lock = True
            try:
                yield
            finally:
                inside_lock = False

    def observed_capture(*args: Any, **kwargs: Any):
        assert not inside_lock
        return capture_entry(*args, **kwargs)

    def observed_publication_files(*args: Any, **kwargs: Any):
        assert not inside_lock
        return publication_files(*args, **kwargs)

    def observed_repository_files(*args: Any, **kwargs: Any):
        assert not inside_lock
        return repository_files(*args, **kwargs)

    monkeypatch.setattr(build_module, "view_mutation_lock", observed_lock)
    monkeypatch.setattr(inputs_module, "_capture_entry", observed_capture)
    monkeypatch.setattr(
        publication_module,
        "artifact_files",
        observed_publication_files,
    )
    monkeypatch.setattr(
        repository_module,
        "artifact_files",
        observed_repository_files,
    )

    publish_artifact_lease(project, "development").close()
    publish_artifact_lease(project, "development").close()
    _change_document(project, "next revision")
    publish_artifact_lease(project, "development").close()


def test_cached_restore_rebuilds_a_corrupt_retained_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build
    restore = build_module.restore_cached_artifact
    builds = 0
    with publish_artifact_lease(project, "development") as first:
        document = first.artifact.root / first.artifact.document
        expected = document.read_bytes()

    def corrupt_before_restore(*args: Any, **kwargs: Any) -> ArtifactLease | None:
        document.write_bytes(b"x" * len(expected))
        return restore(*args, **kwargs)

    def observed_build(request: BuildRequest) -> BuildResult:
        nonlocal builds
        builds += 1
        return build(request)

    monkeypatch.setattr(provider, "build", observed_build)
    monkeypatch.setattr(
        build_module,
        "restore_cached_artifact",
        corrupt_before_restore,
    )

    with publish_artifact_lease(project, "development") as rebuilt:
        restored = rebuilt.read_bytes(rebuilt.artifact.document)

    assert builds == 1
    assert restored == expected


@pytest.mark.parametrize("corrupt_receipt", (False, True))
def test_prepared_inspection_errors_block_provider_build_and_cached_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt_receipt: bool,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    with publish_artifact_lease(project, "development") as lease:
        published = lease.artifact
    inspection = provider.inspect(inspection_request(project))
    failure = ProjectDiagnostic(
        code="provider-analysis-failed",
        severity="error",
        message="Provider analysis failed.",
    )
    failed_inspection = replace(inspection, diagnostics=(failure,))
    input_id = project_revision(
        project,
        failed_inspection,
        provider.provenance(failed_inspection),
    )
    if corrupt_receipt:
        _profile_path(project).write_text("{", encoding="utf-8")
    builds = 0

    def build(_request: BuildRequest) -> BuildResult:
        nonlocal builds
        builds += 1
        return BuildResult(PurePosixPath("index.html"), ())

    monkeypatch.setattr(provider, "build", build)

    with pytest.raises(ViewProjectError, match="Provider analysis failed"):
        publish_artifact_lease(
            project,
            "development",
            inspection=failed_inspection,
            input_id=input_id,
        )

    state = read_build_state(project, "development")
    assert builds == 0
    assert input_id == published.project_revision
    assert state.phase == "failed"
    if not corrupt_receipt:
        assert state.artifact_revision == published.artifact_revision
    assert state.project_revision == input_id
    assert state.diagnostics == (failure,)


def test_last_good_artifact_leasing_stays_available_during_provider_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    first_lease = publish_artifact_lease(project, "development")
    first = first_lease.artifact
    first_lease.close()
    _change_document(project, "next generation")
    provider = provider_registry().get(project.provider)
    build = provider.build
    entered = Event()
    release = Event()

    def wait_during_build(request: BuildRequest) -> BuildResult:
        entered.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test build was not released")
        return build(request)

    monkeypatch.setattr(provider, "build", wait_during_build)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            publish_artifact_lease,
            project,
            "development",
        )
        assert entered.wait(timeout=2)
        retained = lease_published_artifact(project, "development")
        state = read_artifact_state(project, "development")
        assert not future.done()
        release.set()
        built = future.result(timeout=5)

    assert retained is not None
    assert state.artifact is not None
    assert state.state is not None and state.state.published is not None
    assert state.artifact.artifact_revision == first.artifact_revision
    assert state.state.published.artifact_revision == first.artifact_revision
    assert state.build.phase == "building"
    assert state.build.artifact_revision == first.artifact_revision
    retained.close()
    built.close()


def test_manifest_write_failure_records_a_failed_attempt_and_keeps_last_good(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    first = publish_artifact(project, "development")
    _change_document(project, "next generation")
    atomic_write_text = publication_module.atomic_write_text

    def fail_manifest(
        path: Path,
        content: str,
        *,
        root: Path | None = None,
    ) -> None:
        if path.name == "artifact.json":
            raise OSError("artifact manifest write failed")
        atomic_write_text(path, content, root=root)

    monkeypatch.setattr(publication_module, "atomic_write_text", fail_manifest)

    with pytest.raises(ViewProjectError, match="artifact manifest write failed"):
        publish_artifact(project, "development")

    state = read_artifact_state(project, "development")
    assert state.artifact is not None
    assert state.artifact.artifact_revision == first.artifact_revision
    assert state.build.phase == "failed"
    assert [item.code for item in state.build.diagnostics] == [
        "artifact-publication-failed"
    ]


@pytest.mark.parametrize("cache_hit", (False, True))
def test_prune_failure_does_not_leave_an_unreturned_artifact_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_hit: bool,
) -> None:
    project = _project(tmp_path)
    if cache_hit:
        publish_artifact_lease(project, "development").close()

    def fail_prune(_project: ViewProject) -> None:
        raise RuntimeError("forced prune failure")

    monkeypatch.setattr(retention_module, "prune_artifacts_locked", fail_prune)

    with pytest.raises(
        (RuntimeError, ViewProjectError),
        match="forced prune failure",
    ):
        publish_artifact_lease(project, "development")

    pins = artifact_root(project) / ".pins"
    assert not pins.exists() or not tuple(pins.glob("*/*"))


def test_provider_build_reads_one_immutable_input_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    live_document = project.root / "index.html"
    source_a = live_document.read_text(encoding="utf-8").replace(
        "</main>", "<p>generation-a</p></main>"
    )
    source_b = source_a.replace("generation-a", "generation-b")
    live_document.write_text(source_a, encoding="utf-8")
    provider = provider_registry().get(project.provider)

    def build_from_snapshot(request: BuildRequest) -> BuildResult:
        assert request.project.root != project.root
        assert request.cache_root == artifact_root(project) / ".cache"
        assert request.cache_root.is_dir()
        live_document.write_text(source_b, encoding="utf-8")
        snapshot_document = request.project.root / "index.html"
        assert snapshot_document.read_text(encoding="utf-8") == source_a
        shutil.copy2(snapshot_document, request.staging_root / "index.html")
        live_document.write_text(source_a, encoding="utf-8")
        return BuildResult(PurePosixPath("index.html"), ())

    monkeypatch.setattr(provider, "build", build_from_snapshot)
    with publish_artifact_lease(project, "development") as lease:
        document = lease.read_text(lease.artifact.document)

    assert document == source_a


def test_build_request_receives_the_owner_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    build = provider.build
    cancellation = ProviderCancellation()

    def capture_cancellation(request: BuildRequest) -> BuildResult:
        assert request.cancellation is cancellation
        return build(request)

    monkeypatch.setattr(provider, "build", capture_cancellation)
    with provider_cancellation(cancellation):
        lease = publish_artifact_lease(project, "development")

    lease.close()


@pytest.mark.parametrize("relative", ("index.html", "view.toml"))
def test_publish_rechecks_live_inputs_after_snapshot_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    project = _project(tmp_path)
    live_document = project.root / relative
    provider = provider_registry().get(project.provider)
    build = provider.build

    def change_live_input(request: BuildRequest) -> BuildResult:
        report = build(request)
        content = live_document.read_text(encoding="utf-8")
        changed = (
            content.replace("</main>", "<p>changed</p></main>")
            if relative == "index.html"
            else f"{content}# changed during build\n"
        )
        live_document.write_text(changed, encoding="utf-8")
        return report

    monkeypatch.setattr(provider, "build", change_live_input)

    with pytest.raises(ViewProjectError, match="changed while its artifact was built"):
        publish_artifact_lease(project, "development")

    assert read_published_artifact(project, "development") is None


def test_prepared_cache_rechecks_source_before_reporting_success(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    with publish_artifact_lease(project, "development") as lease:
        published = lease.artifact
    provider = provider_registry().get(project.provider)
    inspection = provider.inspect(inspection_request(project))
    input_id = project_revision(
        project,
        inspection,
        provider.provenance(inspection),
    )
    _change_document(project, "changed before prepared cache reuse")

    with pytest.raises(ViewProjectError, match="changed while its artifact was built"):
        publish_artifact_lease(
            project,
            "development",
            inspection=inspection,
            input_id=input_id,
        )

    retained = read_published_artifact(project, "development")
    assert retained is not None
    assert retained.artifact_revision == published.artifact_revision
    state = read_build_state(project, "development")
    assert state.phase == "failed"
    assert [item.code for item in state.diagnostics] == ["project-changed-during-build"]


def test_cached_restore_confirms_source_inside_its_receipt_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    with publish_artifact_lease(project, "development") as lease:
        published = lease.artifact
    restore = build_module.restore_cached_artifact
    document = project.root / "index.html"

    def change_before_restore(*args: Any, **kwargs: Any) -> ArtifactLease | None:
        _change_document(project, "changed at cached restore")
        return restore(*args, **kwargs)

    monkeypatch.setattr(build_module, "restore_cached_artifact", change_before_restore)

    with pytest.raises(ViewProjectError, match="changed while its artifact was built"):
        publish_artifact_lease(project, "development")

    assert "changed at cached restore" in document.read_text(encoding="utf-8")
    retained = read_published_artifact(project, "development")
    assert retained is not None
    assert retained.artifact_revision == published.artifact_revision


def test_publication_confirms_source_inside_its_receipt_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    with publish_artifact_lease(project, "development") as lease:
        published = lease.artifact
    _change_document(project, "candidate generation")
    commit = build_module.publish_artifact_candidate

    def change_before_commit(*args: Any, **kwargs: Any) -> ArtifactLease:
        _change_document(project, "changed at publication commit")
        return commit(*args, **kwargs)

    monkeypatch.setattr(
        build_module,
        "publish_artifact_candidate",
        change_before_commit,
    )

    with pytest.raises(ViewProjectError, match="changed while its artifact was built"):
        publish_artifact_lease(project, "development")

    retained = read_published_artifact(project, "development")
    assert retained is not None
    assert retained.artifact_revision == published.artifact_revision


def test_publication_revalidates_prehashed_artifact_identity_at_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    commit = build_module.publish_artifact_candidate

    def corrupt_before_commit(*args: Any, **kwargs: Any) -> ArtifactLease:
        prepared = args[2]
        document = prepared.publication_root / "files" / prepared.manifest.document
        document.write_bytes(b"x" * document.stat().st_size)
        return commit(*args, **kwargs)

    monkeypatch.setattr(
        build_module,
        "publish_artifact_candidate",
        corrupt_before_commit,
    )

    with pytest.raises(ViewProjectError, match="changed during commit"):
        publish_artifact_lease(project, "development")

    assert read_published_artifact(project, "development") is None
    state = read_build_state(project, "development")
    assert state.phase == "failed"
    assert [item.code for item in state.diagnostics] == ["artifact-publication-failed"]


@pytest.mark.parametrize("missing", ("inspection", "input_id"))
def test_prepared_build_identity_requires_inspection_and_input_id(
    tmp_path: Path,
    missing: str,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    inspection = provider.inspect(inspection_request(project))
    input_id = project_revision(
        project,
        inspection,
        provider.provenance(inspection),
    )

    with pytest.raises(ConfigurationError, match="require both"):
        publish_artifact_lease(
            project,
            "development",
            inspection=None if missing == "inspection" else inspection,
            input_id=None if missing == "input_id" else input_id,
        )


def test_failed_build_preserves_the_latest_profile_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    first_pin = publish_artifact_lease(project, "development")
    pointer = _profile_path(project)
    first_state = _read_json(pointer)

    document = project.root / "index.html"
    document.write_text(
        document.read_text(encoding="utf-8").replace("</main>", "<p>second</p></main>"),
        encoding="utf-8",
    )
    second = publish_artifact(project, "development")
    second_state = _read_json(pointer)

    _write_json(pointer, first_state)
    document.write_text(
        document.read_text(encoding="utf-8").replace("</main>", "<p>third</p></main>"),
        encoding="utf-8",
    )
    provider = provider_registry().get(project.provider)

    def fail_after_newer_publication(_request: object) -> None:
        _write_json(pointer, second_state)
        raise RuntimeError("stale build failed")

    monkeypatch.setattr(provider, "build", fail_after_newer_publication)
    with pytest.raises(ViewProjectError, match="stale build failed"):
        publish_artifact(project, "development")

    retained = read_published_artifact(project, "development")
    assert retained is not None
    assert retained.artifact_revision == second.artifact_revision
    assert read_build_state(project, "development").phase == "failed"
    first_pin.close()
