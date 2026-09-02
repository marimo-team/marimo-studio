"""Exercise verified artifact serving and presentation lease ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.types import Message, Scope

import marimo_studio._server.presentation.service as presentation_module
import marimo_studio._server.ready_handler as ready_handler_module
import marimo_studio._views.revisions as revisions_module
from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._server.files import artifact_file_response
from marimo_studio._server.ports import ServerAdapters
from marimo_studio._server.presentation.service import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._server.ready_handler import (
    ReadyWorkspaceHandler,
    ReadyWorkspaceRoute,
)
from marimo_studio._server.records import (
    ServerContext,
    ServerHandle,
    ServerLocation,
)
from marimo_studio._server.routing import ArtifactAssetRoute
from marimo_studio._server.runtime.catalog import RuntimeRegistry
from marimo_studio._server.workspace_lifecycle import Ready
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._views.revisions import PresentationSourceSnapshot
from marimo_studio._workspace import load_studio
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import BuildProfile, ViewProject

from ..artifact_test_support import (
    add_provider_outputs as _add_provider_outputs,
)
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


def _finish_response(response: Any) -> None:
    if response.background is not None:
        asyncio.run(response.background())


def _read_response(response: Any) -> bytes:
    async def read() -> bytes:
        chunks = [chunk async for chunk in response.body_iterator]
        if response.background is not None:
            await response.background()
        return b"".join(chunks)

    return asyncio.run(read())


class _LeaseCloser:
    def __init__(
        self,
        name: str,
        calls: list[str],
        failure: BaseException | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.failure = failure
        self.closed = False

    def close(self) -> None:
        self.calls.append(self.name)
        self.closed = True
        if self.failure is not None:
            raise self.failure


def _presentation_snapshot(view_name: str, revision: str) -> PresentationSnapshot:
    return cast(
        PresentationSnapshot,
        SimpleNamespace(
            view_name=view_name,
            revision=revision,
            artifact=SimpleNamespace(
                profile="development",
                artifact_revision=revision,
            ),
        ),
    )


def _artifact_route(
    notebook_path: Path,
) -> tuple[ReadyWorkspaceHandler, ReadyWorkspaceRoute, NotebookPresentation]:
    prepare_view(notebook_path)
    presentation = NotebookPresentation(notebook_path)
    snapshot = presentation.snapshot("dashboard")
    definition = presentation.discover_definition()
    assert definition is not None
    workspace = presentation.materialize(definition)
    handle = ServerHandle(object())
    context = ServerContext(
        notebook=notebook_path,
        file_key=str(notebook_path),
        base_url="",
        mode="run",
        dev=False,
        routing_query=(),
        user_config={},
        config_overrides={},
        server_token="test-token",
        handle=handle,
    )
    location = ServerLocation(
        notebook=notebook_path,
        file_key=str(notebook_path),
        base_url="",
        mode="run",
        routing_query=(),
        handle=handle,
    )
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/dashboard/artifact",
        "raw_path": b"/dashboard/artifact",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 80),
    }
    route = ReadyWorkspaceRoute(
        scope=scope,
        request=Request(scope),
        context=context,
        location=location,
        notebook_scope=cast(
            Any,
            SimpleNamespace(presentation=presentation, clients=SimpleNamespace()),
        ),
        lifecycle=Ready(definition, workspace),
        relative="/dashboard/artifact",
        landing=False,
        request_view="dashboard",
        authored=None,
        selected_document=None,
        selected_studio=None,
        selected_asset=ArtifactAssetRoute(
            view="dashboard",
            revision=snapshot.artifact.artifact_revision,
            asset=snapshot.artifact.document.as_posix(),
        ),
        presentation_session=None,
        capability=None,
    )
    adapters = cast(
        ServerAdapters,
        SimpleNamespace(peer_commands=SimpleNamespace(enable=lambda _location: None)),
    )
    return (
        ReadyWorkspaceHandler(adapters, cast(RuntimeRegistry, object())),
        route,
        presentation,
    )


async def _request_body() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _discard_message(_message: Message) -> None:
    return


def _cancel_request(
    handler: ReadyWorkspaceHandler,
    route: ReadyWorkspaceRoute,
    started: Event,
    release: Event,
) -> None:
    async def exercise() -> None:
        task = asyncio.create_task(
            handler.handle(route, _request_body, _discard_message)
        )
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


def test_artifact_route_closes_response_owners_after_disconnect(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler, route, presentation = _artifact_route(notebook_path)
    original = presentation.lease_artifact
    try:
        acquisition_started = Event()
        acquisition_release = Event()
        acquisition: list[ArtifactLease] = []

        def acquire_after_disconnect(view: str, revision: str) -> ArtifactLease | None:
            acquisition_started.set()
            if not acquisition_release.wait(timeout=2):
                raise RuntimeError("Artifact acquisition was not released")
            lease = original(view, revision)
            if lease is not None:
                acquisition.append(lease)
            return lease

        with monkeypatch.context() as patch:
            patch.setattr(presentation, "lease_artifact", acquire_after_disconnect)
            _cancel_request(
                handler,
                route,
                acquisition_started,
                acquisition_release,
            )
        assert len(acquisition) == 1
        assert acquisition[0].closed

        preparation_started = Event()
        preparation_release = Event()
        prepared: list[Any] = []
        preparation: list[ArtifactLease] = []
        prepare = ready_handler_module.artifact_file_response

        def acquire_for_preparation(view: str, revision: str) -> ArtifactLease | None:
            lease = original(view, revision)
            if lease is not None:
                preparation.append(lease)
            return lease

        def prepare_after_disconnect(
            lease: ArtifactLease,
            relative: str,
            *,
            head: bool = False,
            if_none_match: str | None = None,
        ) -> Any:
            preparation_started.set()
            if not preparation_release.wait(timeout=2):
                raise RuntimeError("Artifact response preparation was not released")
            response = prepare(
                lease,
                relative,
                head=head,
                if_none_match=if_none_match,
            )
            prepared.append(response)
            return response

        with monkeypatch.context() as patch:
            patch.setattr(
                ready_handler_module,
                "artifact_file_response",
                prepare_after_disconnect,
            )
            patch.setattr(presentation, "lease_artifact", acquire_for_preparation)
            _cancel_request(
                handler,
                route,
                preparation_started,
                preparation_release,
            )
        assert len(prepared) == 1
        assert len(preparation) == 1
        assert preparation[0].closed

        sent: list[ArtifactLease] = []

        def acquire_for_send(view: str, revision: str) -> ArtifactLease | None:
            lease = original(view, revision)
            if lease is not None:
                sent.append(lease)
            return lease

        async def disconnect(_message: Message) -> None:
            raise asyncio.CancelledError

        with monkeypatch.context() as patch:
            patch.setattr(presentation, "lease_artifact", acquire_for_send)

            async def exercise_send() -> None:
                with pytest.raises(asyncio.CancelledError):
                    await handler.handle(route, _request_body, disconnect)

            asyncio.run(exercise_send())
        assert len(sent) == 1
        assert sent[0].closed
    finally:
        presentation.close()


def test_artifact_serving_requires_manifest_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    _add_provider_outputs(
        monkeypatch,
        project,
        {PurePosixPath("app.css"): b"body { color: black; }\n"},
    )
    owner = publish_artifact_lease(project, "development")
    artifact = owner.artifact
    (artifact.root / "unlisted.js").write_text("unlisted", encoding="utf-8")

    with owner:
        unlisted = owner.share()
        assert artifact_file_response(unlisted, "unlisted.js").status_code == 404
        assert unlisted.closed
        traversal = owner.share()
        assert artifact_file_response(traversal, "../index.html").status_code == 404
        assert traversal.closed
        document_lease = owner.share()
        document_response = artifact_file_response(
            document_lease, artifact.document.as_posix()
        )
        assert document_response.status_code == 200
        assert not document_lease.closed
        _finish_response(document_response)
        assert document_lease.closed
        stylesheet_lease = owner.share()
        stylesheet = artifact_file_response(stylesheet_lease, "app.css")
        assert stylesheet.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")
        assert not stylesheet_lease.closed
        _finish_response(stylesheet)
        assert stylesheet_lease.closed
        head_lease = owner.share()
        head = artifact_file_response(
            head_lease,
            artifact.document.as_posix(),
            head=True,
        )
        document_file = next(
            item for item in artifact.files if item.path == artifact.document
        )
        assert head.body == b""
        assert head.headers["content-length"] == str(document_file.size)
        assert not head_lease.closed
        _finish_response(head)
        assert head_lease.closed


@pytest.mark.parametrize(
    ("damage", "method"),
    (("missing", "get"), ("size", "head"), ("same-size", "validator")),
)
def test_artifact_responses_require_verified_bytes(
    tmp_path: Path,
    damage: str,
    method: str,
) -> None:
    project = _project(tmp_path)
    owner = publish_artifact_lease(project, "development")
    artifact = owner.artifact
    document = artifact.root / artifact.document
    record = next(item for item in artifact.files if item.path == artifact.document)
    if damage == "missing":
        document.unlink()
    elif damage == "same-size":
        document.write_bytes(b"x" * record.size)
    else:
        document.write_bytes(b"x" * (record.size + 1))

    with owner:
        response = artifact_file_response(
            owner.share(),
            artifact.document.as_posix(),
            head=method == "head",
            if_none_match=(
                f'"sha256:{record.sha256}"' if method == "validator" else None
            ),
        )

    assert response.status_code == 404
    assert "etag" not in response.headers
    state = read_build_state(project, "development")
    assert state.phase == "stale"
    assert state.diagnostics[0].code == "artifact-integrity-failed"


def test_artifact_corruption_marks_the_publication_stale_and_rebuilds(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    owner = publish_artifact_lease(project, "development")
    artifact = owner.artifact
    document = artifact.root / artifact.document
    record = next(item for item in artifact.files if item.path == artifact.document)
    document.write_bytes(b"x" * record.size)

    with owner:
        response = artifact_file_response(
            owner.share(),
            artifact.document.as_posix(),
        )
        state = read_build_state(project, "development")
        rebuilt = publish_artifact(project, "development")

    assert response.status_code == 404
    assert state.phase == "stale"
    assert state.diagnostics[0].code == "artifact-integrity-failed"
    assert next(
        item for item in rebuilt.files if item.path == rebuilt.document
    ).sha256 == (record.sha256)


def test_corrupt_sibling_receipt_does_not_block_integrity_state(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    owner = publish_artifact_lease(project, "production")
    _profile_path(project).write_text("{", encoding="utf-8")
    document = owner.artifact.root / owner.artifact.document
    document.unlink()

    with owner:
        response = artifact_file_response(
            owner.share(),
            owner.artifact.document.as_posix(),
        )

    assert response.status_code == 404
    state = read_build_state(project, "production")
    assert state.phase == "stale"
    assert state.diagnostics[0].code == "artifact-integrity-failed"


def test_open_response_is_isolated_from_later_source_growth(tmp_path: Path) -> None:
    project = _project(tmp_path)
    owner = publish_artifact_lease(project, "development")
    artifact = owner.artifact
    document = artifact.root / artifact.document
    expected = document.read_bytes()

    with owner:
        response = artifact_file_response(
            owner.share(),
            artifact.document.as_posix(),
        )
        document.write_bytes(expected + b"later growth")
        body = _read_response(response)

    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(expected))
    assert body == expected


def test_presentation_history_pins_revisions_until_scope_release(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    presentation = NotebookPresentation(notebook_path)
    first = presentation.snapshot("dashboard")
    project = load_studio(notebook_path).view("dashboard")
    _change_document(project, "next presentation")
    second = presentation.snapshot("dashboard")

    assert first.artifact.root.parent.is_dir()
    assert second.artifact.root.parent.is_dir()

    presentation.close()

    assert not first.artifact.root.parent.exists()
    assert second.artifact.root.parent.is_dir()


def test_display_snapshot_uses_the_verified_publication_before_validation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    publish_artifact(
        load_studio(notebook_path).view("dashboard"),
        "development",
    )

    def unexpected_validation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("display snapshot started provider validation")

    monkeypatch.setattr(
        presentation_module,
        "capture_presentations",
        unexpected_validation,
    )
    presentation = NotebookPresentation(notebook_path)
    try:
        first = presentation.display_snapshot("dashboard")
        assert first.view_name == "dashboard"
        assert first.document
        project = load_studio(notebook_path).view("dashboard")
        _change_document(project, "new published presentation")
        publish_artifact(project, "development")

        second = presentation.display_snapshot("dashboard")

        assert second.revision != first.revision
        assert "new published presentation" in second.document
    finally:
        presentation.close()


@pytest.mark.parametrize(
    ("corruption", "message"),
    (
        ("document", "does not match its manifest"),
        ("extra", "file tree does not match its manifest"),
    ),
)
def test_presentation_rejects_artifact_corruption_before_document_read(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    message: str,
) -> None:
    prepare_view(notebook_path)
    verify_membership = ArtifactLease.verify_membership
    corrupted = False

    def corrupt_then_verify(lease: ArtifactLease) -> None:
        nonlocal corrupted
        if not corrupted:
            corrupted = True
            if corruption == "document":
                document = lease.artifact.root / lease.artifact.document
                document.write_bytes(b"x" * document.stat().st_size)
            else:
                lease.artifact.root.joinpath("unlisted.js").write_text(
                    "unlisted",
                    encoding="utf-8",
                )
        verify_membership(lease)

    monkeypatch.setattr(ArtifactLease, "verify_membership", corrupt_then_verify)
    presentation = NotebookPresentation(notebook_path)
    try:
        with pytest.raises(ConfigurationError, match=message):
            presentation.snapshot("dashboard")
    finally:
        presentation.close()

    project = load_studio(notebook_path).view("dashboard")
    state = read_build_state(project, "development")
    assert corrupted
    assert state.phase == "stale"
    assert state.diagnostics[0].code == "artifact-integrity-failed"


def test_presentation_close_releases_every_lease_after_one_fails(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    first = _LeaseCloser("first", calls, RuntimeError("first close failed"))
    second = _LeaseCloser("second", calls)
    presentation = NotebookPresentation(tmp_path / "analysis.py")
    first_snapshot = _presentation_snapshot("dashboard", "first")
    second_snapshot = _presentation_snapshot("dashboard", "second")
    presentation._remember(first_snapshot, cast(ArtifactLease, first))
    presentation._remember(second_snapshot, cast(ArtifactLease, second))

    with pytest.raises(RuntimeError, match="first close failed"):
        presentation.close()

    assert presentation.snapshot_for_revision("dashboard", "first") is None
    assert presentation.snapshot_for_revision("dashboard", "second") is None
    presentation.close()
    assert sorted(calls) == ["first", "second"]
    assert first.closed
    assert second.closed


def test_presentation_snapshot_releases_every_removed_view_lease(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    calls: list[str] = []
    first = _LeaseCloser("first", calls, RuntimeError("prune close failed"))
    second = _LeaseCloser("second", calls)
    presentation = NotebookPresentation(notebook_path)
    presentation._remember(
        _presentation_snapshot("removed", "first"),
        cast(ArtifactLease, first),
    )
    presentation._remember(
        _presentation_snapshot("removed", "second"),
        cast(ArtifactLease, second),
    )

    with pytest.raises(RuntimeError, match="prune close failed"):
        presentation.snapshot("dashboard")

    assert presentation.snapshot_for_revision("removed", "first") is None
    assert presentation.snapshot_for_revision("removed", "second") is None
    presentation.close()
    assert sorted(calls) == ["first", "second"]


def test_presentation_replacement_keeps_the_new_lease_when_old_close_fails(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    old = _LeaseCloser("old", calls, RuntimeError("replacement close failed"))
    new = _LeaseCloser("new", calls)
    old_snapshot = _presentation_snapshot("dashboard", "revision")
    new_snapshot = _presentation_snapshot("dashboard", "revision")
    presentation = NotebookPresentation(tmp_path / "analysis.py")
    presentation._remember(old_snapshot, cast(ArtifactLease, old))

    with pytest.raises(RuntimeError, match="replacement close failed"):
        presentation._remember(new_snapshot, cast(ArtifactLease, new))

    assert calls == ["old"]
    assert old.closed
    assert not new.closed
    assert presentation.snapshot_for_revision("dashboard", "revision") is new_snapshot

    presentation.close()
    assert calls == ["old", "new"]
    assert new.closed


def test_presentation_revisited_revision_becomes_most_recent() -> None:
    calls: list[str] = []
    presentation = NotebookPresentation(Path("analysis.py"))
    leases: dict[str, _LeaseCloser] = {}
    snapshots: dict[str, PresentationSnapshot] = {}

    def remember(revision: str, lease_name: str | None = None) -> None:
        lease = _LeaseCloser(lease_name or revision, calls)
        leases[lease.name] = lease
        snapshot = _presentation_snapshot("dashboard", revision)
        snapshots[revision] = snapshot
        presentation._remember(snapshot, cast(ArtifactLease, lease))

    for index in range(8):
        remember(f"revision-{index}")
    remember("revision-0", "revision-0-revisited")
    remember("revision-8")

    assert leases["revision-0"].closed
    assert leases["revision-1"].closed
    assert presentation.snapshot_for_revision("dashboard", "revision-1") is None
    for revision in (
        "revision-0",
        "revision-2",
        "revision-3",
        "revision-4",
        "revision-5",
        "revision-6",
        "revision-7",
        "revision-8",
    ):
        assert (
            presentation.snapshot_for_revision("dashboard", revision)
            is snapshots[revision]
        )
    for lease_name in (
        "revision-0-revisited",
        "revision-2",
        "revision-3",
        "revision-4",
        "revision-5",
        "revision-6",
        "revision-7",
        "revision-8",
    ):
        assert not leases[lease_name].closed

    presentation.close()
    assert all(lease.closed for lease in leases.values())


def test_presentation_source_snapshot_closes_every_lease_after_failure() -> None:
    calls: list[str] = []
    first = _LeaseCloser("first", calls, RuntimeError("snapshot close failed"))
    second = _LeaseCloser("second", calls)
    snapshot = PresentationSourceSnapshot(
        leases={
            "first": cast(ArtifactLease, first),
            "second": cast(ArtifactLease, second),
        },
        notebook_source="",
        base_identity=(),
    )

    with pytest.raises(RuntimeError, match="snapshot close failed"):
        snapshot.close()

    snapshot.close()
    assert sorted(calls) == ["first", "second"]
    assert snapshot.leases == {}


def test_presentation_capture_retains_construction_error_after_cleanup_failures(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    prepare_view(notebook_path, "operations")
    studio = load_studio(notebook_path)
    calls: list[str] = []
    leases = {
        "dashboard": _LeaseCloser(
            "dashboard",
            calls,
            RuntimeError("cleanup failed"),
        ),
        "executive": _LeaseCloser("executive", calls),
    }

    def publish(
        project: ViewProject,
        _profile: BuildProfile,
        *,
        expected_generation: str | None = None,
    ) -> ArtifactLease:
        _ = expected_generation
        if project.name == "operations":
            raise RuntimeError("construction failed")
        return cast(ArtifactLease, leases[project.name])

    monkeypatch.setattr(revisions_module, "publish_view", publish)

    with pytest.raises(RuntimeError, match="construction failed"):
        revisions_module.capture_presentations(studio)

    assert set(calls) == {"dashboard", "executive"}
