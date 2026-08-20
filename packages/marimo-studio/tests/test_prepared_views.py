from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from marimo_export import ExportRepository
from marimo_export.errors import CaptureLimitError, ExecutionError
from marimo_export.repository import RepositoryLimitError
from marimo_export.wire import state_fingerprint
from starlette.requests import Request

from marimo_studio._server.prepared_views import (
    PreparedView,
    PreparedViewRegistry,
    PreparedViewRequest,
)
from marimo_studio._server.presentation import PresentationSnapshot
from marimo_studio._server.studio.view_compiler import compile_export_view
from marimo_studio._server.zero_python_api import zero_python_response
from marimo_studio.errors import PublicationError, PublicationLimitError


class _Repository:
    def __init__(self) -> None:
        self.observations: list[tuple[str, dict[str, object]]] = []
        self.revision = 0
        self.closed = False

    def record_observation(
        self,
        plan: object,
        inputs: Mapping[str, object],
    ) -> object:
        self.revision += 1
        producer_sha256 = cast(str, cast(Any, plan).producer_sha256)
        self.observations.append((producer_sha256, dict(inputs)))
        return SimpleNamespace(values=inputs, revision=self.revision)

    def observation_revision(self, plan: object) -> int:
        assert cast(Any, plan).producer_sha256 == "a" * 64
        return self.revision

    def close(self) -> None:
        self.closed = True


class _PreparedAsset:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Prepared:
    def __init__(
        self,
        root: Path,
        instance: int,
        inputs: tuple[str, ...],
        observation_revision: int,
    ) -> None:
        self.identity = f"{instance:064x}"
        self.path = root / self.identity
        self.path.mkdir(parents=True)
        self.path.joinpath("index.json").write_text("{}", encoding="utf-8")
        self.path.joinpath("assets").mkdir()
        self.path.joinpath("assets/value.bin").write_bytes(b"value")
        self.plan = SimpleNamespace(
            document_sha256="d" * 64,
            inputs=inputs,
            producer_sha256="a" * 64,
            observation_revision=observation_revision,
        )
        self.closed = False
        self.renewals = 0
        self.manifest_calls: list[tuple[str, object, int | None]] = []
        self.assets: list[_PreparedAsset] = []

    def manifest(
        self,
        export_url: str,
        *,
        state: object = None,
        refresh_interval_ms: int | None = None,
    ) -> dict[str, object]:
        self.manifest_calls.append((export_url, state, refresh_interval_ms))
        return {
            "schema": "marimo-export.prepared.v1",
            "instance": self.identity,
            "export_url": export_url,
            "inputs": state if state is not None else {},
            "state_fingerprint": "e" * 64,
            **(
                {"refresh_interval_ms": refresh_interval_ms}
                if refresh_interval_ms is not None
                else {}
            ),
        }

    def renew(self) -> None:
        if self.closed:
            raise RuntimeError("prepared export is closed")
        self.renewals += 1

    def asset(self, relative: str) -> _PreparedAsset:
        if self.closed:
            raise RuntimeError("prepared export is closed")
        candidate = self.path / relative
        if not candidate.is_file():
            raise RuntimeError("prepared asset is unavailable")
        asset = _PreparedAsset(candidate)
        self.assets.append(asset)
        return asset

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(
        self,
        root: Path,
        instance: int,
        *,
        current: Mapping[str, object] | None = None,
        observations: tuple[object, ...] = (),
        capture: Callable[[Any, Callable[[], bool]], _Prepared] | None = None,
    ) -> None:
        self.root = root
        self.instance = instance
        self.current = dict(current or {"x": instance})
        self.observations = observations
        self.capture_callback = capture
        self.captured_specs: list[Any] = []
        self.prepared: list[_Prepared] = []

    def plan(self, *, spec: Any, repository: Any) -> object:
        del repository
        return SimpleNamespace(
            producer_sha256="a" * 64,
            document_sha256="d" * 64,
            inputs=("x",),
            observations=self.observations,
            states=tuple(
                SimpleNamespace(
                    inputs=values,
                    fingerprint=state_fingerprint(values),
                )
                for values in spec.states.values()
            ),
        )

    def observe_inputs(self) -> object:
        return SimpleNamespace(values=self.current)

    def capture(
        self,
        *,
        spec: Any,
        repository: Any,
        cancelled: Callable[[], bool],
    ) -> _Prepared:
        self.captured_specs.append(spec)
        if self.capture_callback is not None:
            prepared = self.capture_callback(spec, cancelled)
        else:
            prepared = _Prepared(
                self.root,
                self.instance,
                tuple(sorted(self.current)),
                repository.revision,
            )
        self.prepared.append(prepared)
        return prepared


class _Client:
    def __init__(self, session: _Session) -> None:
        self._session = session

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_error: object) -> None:
        return None

    def session(self, session_id: str) -> _Session:
        assert session_id == "s_123456"
        return self._session


class _Connector:
    def __init__(self, *sessions: _Session) -> None:
        self._sessions = iter(sessions)
        self.calls = 0

    def __call__(self, server: str, **options: object) -> _Client:
        self.calls += 1
        assert server == "http://127.0.0.1:4312/"
        assert options == {"server_token": "server-token"}
        return _Client(next(self._sessions))


def _snapshot(notebook: Path) -> PresentationSnapshot:
    view_root = notebook.parent / "dashboard"
    view_root.mkdir(exist_ok=True)
    return cast(
        PresentationSnapshot,
        SimpleNamespace(
            view_name="dashboard",
            revision="c" * 64,
            value_references={
                "doubled": SimpleNamespace(source="doubled"),
            },
            output_references={
                "doubled": SimpleNamespace(source="doubled"),
            },
            resolved=SimpleNamespace(
                views={
                    "dashboard": SimpleNamespace(
                        cell_aliases=("summary",),
                        view=SimpleNamespace(root=view_root),
                    )
                },
                aliases={
                    "summary": SimpleNamespace(
                        runtime_id="cell-summary",
                        name=None,
                    )
                },
            ),
        ),
    )


def _request(
    snapshot: PresentationSnapshot,
    *,
    binding: str = "browser-client-1234",
) -> PreparedViewRequest:
    return PreparedViewRequest(
        snapshot=snapshot,
        server="http://127.0.0.1:4312/",
        server_token="server-token",
        session_id="s_123456",
        binding_id=binding,
    )


def _selected_view(
    registry: PreparedViewRegistry,
    snapshot: PresentationSnapshot,
    *,
    poll: bool = False,
) -> PreparedView:
    selected = (
        registry.poll_current(
            "dashboard",
            "browser-client-1234",
            snapshot.revision,
        )
        if poll
        else registry.current(
            "dashboard",
            "browser-client-1234",
            snapshot.revision,
        )
    )
    assert selected is not None
    return selected


def _http_request(snapshot: PresentationSnapshot) -> Request:
    path = "/_marimo-studio/views/dashboard/zero-python/current"
    query = (
        "file=analysis.py&marimo_studio_client=browser-client-1234&"
        f"revision={snapshot.revision}"
    )
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
        }
    )


def test_prepare_current_release_and_close_own_public_handles(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    repository = _Repository()
    session = _Session(notebook_path.parent / "prepared", 1)
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, repository),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> _Prepared:
        selected = await registry.prepare(_request(snapshot))
        prepared = session.prepared[-1]
        assert _selected_view(registry, snapshot).prepared is selected.prepared
        registry.release_binding("browser-client-1234")
        assert (
            registry.current("dashboard", "browser-client-1234", snapshot.revision)
            is None
        )
        assert prepared.closed
        await registry.close()
        return prepared

    prepared = asyncio.run(scenario())

    assert prepared.closed
    assert repository.closed is False


def test_registry_lazily_opens_and_closes_its_export_repository(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(notebook_path)
    repository = _Repository()
    session = _Session(notebook_path.parent / "prepared", 13)
    monkeypatch.setattr(
        ExportRepository,
        "open",
        classmethod(lambda _cls: cast(ExportRepository, repository)),
    )
    registry = PreparedViewRegistry(
        notebook_path,
        connector=cast(Any, _Connector(session)),
    )
    assert not registry.active

    async def scenario() -> None:
        await registry.prepare(_request(snapshot))
        assert registry.active
        await registry.close()
        assert not registry.active

    asyncio.run(scenario())

    assert repository.closed


def test_observations_and_current_inputs_become_explicit_states(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    repository = _Repository()
    observation = SimpleNamespace(fingerprint="b" * 64, values={"x": 2})
    session = _Session(
        notebook_path.parent / "prepared",
        2,
        current={"x": 3},
        observations=(observation,),
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, repository),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> None:
        await registry.prepare(_request(snapshot))
        await registry.close()

    asyncio.run(scenario())

    spec = session.captured_specs[0]
    assert spec.default_state == "baseline"
    assert {name: dict(values) for name, values in spec.states.items()} == {
        "baseline": {"x": 3},
        f"observed-{'b' * 64}": {"x": 2},
    }
    assert repository.observations == [("a" * 64, {"x": 3})]


def test_live_states_keep_bool_and_number_observations_distinct(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    observed = {"x": 1}
    fingerprint = state_fingerprint(observed)
    session = _Session(
        notebook_path.parent / "prepared",
        2,
        current={"x": True},
        observations=(SimpleNamespace(fingerprint=fingerprint, values=observed),),
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> None:
        await registry.prepare(_request(snapshot))
        await registry.close()

    asyncio.run(scenario())

    spec = session.captured_specs[0]
    assert {name: dict(values) for name, values in spec.states.items()} == {
        "baseline": {"x": True},
        f"observed-{fingerprint}": {"x": 1},
    }


def test_saved_export_states_are_the_explicit_capture_contract(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    saved = compile_export_view(
        snapshot,
        states={"baseline": {"x": 1}, "selected": {"x": 2}},
        default_state="selected",
    )
    source = snapshot.resolved.views["dashboard"].view.root / "export.yaml"
    source.write_text(
        yaml.safe_dump(saved.spec.to_value(), sort_keys=False),
        encoding="utf-8",
    )
    repository = _Repository()
    observation = SimpleNamespace(fingerprint="b" * 64, values={"x": 9})
    session = _Session(
        notebook_path.parent / "prepared",
        3,
        current={"x": 2},
        observations=(observation,),
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, repository),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> _Prepared:
        selected = await registry.prepare(_request(snapshot))
        prepared = session.prepared[-1]
        selected.manifest("./export/")
        await registry.close()
        return prepared

    prepared = asyncio.run(scenario())

    spec = session.captured_specs[0]
    assert spec.default_state == "selected"
    assert {name: dict(values) for name, values in spec.states.items()} == {
        "baseline": {"x": 1},
        "selected": {"x": 2},
    }
    assert prepared.manifest_calls[-1][1] == {"x": 2}
    assert repository.observations == [("a" * 64, {"x": 2})]


def test_saved_number_state_does_not_select_live_bool_inputs(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    saved = compile_export_view(
        snapshot,
        states={"number": {"x": 1}},
        default_state="number",
    )
    source = snapshot.resolved.views["dashboard"].view.root / "export.yaml"
    source.write_text(
        yaml.safe_dump(saved.spec.to_value(), sort_keys=False),
        encoding="utf-8",
    )
    session = _Session(
        notebook_path.parent / "prepared",
        3,
        current={"x": True},
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> _Prepared:
        selected = await registry.prepare(_request(snapshot))
        prepared = session.prepared[-1]
        selected.manifest("./export/")
        await registry.close()
        return prepared

    prepared = asyncio.run(scenario())

    assert {
        name: dict(values) for name, values in session.captured_specs[0].states.items()
    } == {"number": {"x": 1}}
    assert prepared.manifest_calls[-1][1] is None


def test_cancelled_caller_settles_blocking_capture_without_publishing(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    started = threading.Event()

    def capture(_spec: object, cancelled: Callable[[], bool]) -> _Prepared:
        started.set()
        while not cancelled():
            threading.Event().wait(0.005)
        raise asyncio.CancelledError

    session = _Session(
        notebook_path.parent / "prepared",
        1,
        capture=capture,
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> None:
        preparing = asyncio.create_task(registry.prepare(_request(snapshot)))
        assert await asyncio.to_thread(started.wait, 2)
        preparing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await preparing
        assert (
            registry.current("dashboard", "browser-client-1234", snapshot.revision)
            is None
        )
        await registry.close()

    asyncio.run(scenario())


def test_new_revision_supersedes_older_work(
    notebook_path: Path,
) -> None:
    first_snapshot = _snapshot(notebook_path)
    second_snapshot = cast(
        PresentationSnapshot,
        SimpleNamespace(**{**vars(first_snapshot), "revision": "f" * 64}),
    )
    started = threading.Event()

    def blocked(_spec: object, cancelled: Callable[[], bool]) -> _Prepared:
        started.set()
        while not cancelled():
            threading.Event().wait(0.005)
        raise asyncio.CancelledError

    first = _Session(notebook_path.parent / "prepared", 1, capture=blocked)
    second = _Session(notebook_path.parent / "prepared", 2)
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(first, second)),
    )

    async def scenario() -> None:
        older = asyncio.create_task(registry.prepare(_request(first_snapshot)))
        assert await asyncio.to_thread(started.wait, 2)
        newest = await registry.prepare(_request(second_snapshot))
        with pytest.raises(asyncio.CancelledError):
            await older
        assert (
            registry.current(
                "dashboard", "browser-client-1234", first_snapshot.revision
            )
            is None
        )
        assert _selected_view(registry, second_snapshot).prepared is newest.prepared
        await registry.close()

    asyncio.run(scenario())


def test_failed_refresh_preserves_last_good_handle(notebook_path: Path) -> None:
    snapshot = _snapshot(notebook_path)
    first = _Session(notebook_path.parent / "prepared", 1)

    def failed(_spec: object, _cancelled: Callable[[], bool]) -> _Prepared:
        raise RuntimeError("capture failed")

    second = _Session(notebook_path.parent / "prepared", 2, capture=failed)
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(first, second)),
    )

    async def scenario() -> None:
        selected = await registry.prepare(_request(snapshot))
        prepared = first.prepared[-1]
        with pytest.raises(RuntimeError, match="capture failed"):
            await registry.prepare(_request(snapshot))
        assert _selected_view(registry, snapshot).prepared is selected.prepared
        assert not prepared.closed
        await registry.close()
        assert prepared.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (CaptureLimitError("capture exceeded its byte limit"), PublicationLimitError),
        (
            RepositoryLimitError("repository exceeded its byte limit"),
            PublicationLimitError,
        ),
        (ExecutionError("state execution failed"), PublicationError),
    ),
)
def test_prepare_translates_public_export_failures(
    notebook_path: Path,
    failure: Exception,
    expected: type[PublicationError],
) -> None:
    snapshot = _snapshot(notebook_path)

    def fail(_spec: object, _cancelled: Callable[[], bool]) -> _Prepared:
        raise failure

    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(
            Any,
            _Connector(_Session(notebook_path.parent / "prepared", 1, capture=fail)),
        ),
    )

    async def scenario() -> None:
        with pytest.raises(expected, match=str(failure)):
            await registry.prepare(_request(snapshot))
        await registry.close()

    asyncio.run(scenario())


def test_prepare_preserves_metadata_failure_when_export_close_fails(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)

    class BrokenPlan:
        @property
        def inputs(self) -> tuple[str, ...]:
            raise ExecutionError("metadata failed")

    class BrokenPrepared(_Prepared):
        def __init__(self) -> None:
            super().__init__(notebook_path.parent / "prepared", 20, (), 0)
            self.plan = cast(Any, BrokenPlan())

        def close(self) -> None:
            raise RuntimeError("close failed")

    def capture(_spec: object, _cancelled: Callable[[], bool]) -> _Prepared:
        return BrokenPrepared()

    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(
            Any,
            _Connector(
                _Session(notebook_path.parent / "prepared", 20, capture=capture)
            ),
        ),
    )

    async def scenario() -> None:
        with pytest.raises(PublicationError, match="metadata failed") as raised:
            await registry.prepare(_request(snapshot))
        assert isinstance(raised.value.__cause__, ExecutionError)
        assert isinstance(raised.value.__cause__.__cause__, RuntimeError)
        assert str(raised.value.__cause__.__cause__) == "close failed"
        await registry.close()

    asyncio.run(scenario())


def test_manifest_wraps_exact_core_with_studio_projection_contract(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    session = _Session(
        notebook_path.parent / "prepared",
        7,
        current={"x": 7},
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> dict[str, object]:
        await registry.prepare(_request(snapshot))
        response = await zero_python_response(
            _http_request(snapshot),
            registry,
            "dashboard",
            "current",
            allow_refresh=False,
        )
        assert response.status_code == 200
        assert response.body is not None
        manifest = json.loads(bytes(response.body))
        await registry.close()
        return cast(dict[str, object], manifest)

    manifest = asyncio.run(scenario())

    assert set(manifest) == {
        "schema",
        "prepared",
        "projections",
        "document_sha256",
        "view",
        "plan_digest",
    }
    assert manifest["schema"] == "marimo-studio.prepared.v1"
    assert manifest["document_sha256"] == "d" * 64
    assert manifest["view"] == "dashboard"
    assert cast(dict[str, object], manifest["prepared"]) == {
        "schema": "marimo-export.prepared.v1",
        "instance": f"{7:064x}",
        "export_url": (
            "http://testserver/_marimo-studio/views/dashboard/zero-python/"
            f"{7:064x}/?file=analysis.py"
        ),
        "inputs": {"x": 7},
        "state_fingerprint": "e" * 64,
        "refresh_interval_ms": 1000,
    }
    assert set(cast(dict[str, object], manifest["projections"])) == {
        "cells",
        "outputs",
        "values",
    }
    assert len(cast(str, manifest["plan_digest"])) == 64


def test_generation_file_borrow_outlives_binding_release(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    session = _Session(notebook_path.parent / "prepared", 9)
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> None:
        selected = await registry.prepare(_request(snapshot))
        prepared = session.prepared[-1]
        asset = await registry.publication_asset(
            "dashboard",
            selected.instance,
            "assets/value.bin",
        )
        assert asset is not None and asset.path.read_bytes() == b"value"
        registry.release_binding("browser-client-1234")
        assert prepared.closed
        assert not cast(_PreparedAsset, asset).closed
        assert asset.path.read_bytes() == b"value"
        asset.close()
        assert cast(_PreparedAsset, asset).closed
        await registry.close()

    asyncio.run(scenario())


def test_replaced_generation_stays_available_for_route_grace(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    first_session = _Session(notebook_path.parent / "prepared", 14)
    second_session = _Session(notebook_path.parent / "prepared", 15)
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, _Repository()),
        connector=cast(Any, _Connector(first_session, second_session)),
        route_grace_seconds=60,
    )

    async def scenario() -> None:
        first = await registry.prepare(_request(snapshot))
        first_prepared = first_session.prepared[-1]
        await registry.prepare(_request(snapshot))
        second_prepared = second_session.prepared[-1]
        assert not first_prepared.closed
        old_asset = await registry.publication_asset(
            "dashboard",
            first.instance,
            "index.json",
        )
        assert old_asset is not None
        old_asset.close()
        registry.release_binding("browser-client-1234")
        assert first_prepared.closed
        assert second_prepared.closed
        await registry.close()

    asyncio.run(scenario())


def test_poll_with_unchanged_observation_revision_does_not_replan(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    repository = _Repository()
    session = _Session(notebook_path.parent / "prepared", 10)
    connector = _Connector(session)
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, repository),
        connector=cast(Any, connector),
    )

    async def scenario() -> None:
        selected = await registry.prepare(_request(snapshot))
        assert (
            _selected_view(registry, snapshot, poll=True).prepared is selected.prepared
        )
        await asyncio.sleep(0.05)
        assert connector.calls == 1
        assert _selected_view(registry, snapshot).prepared is selected.prepared
        await registry.close()

    asyncio.run(scenario())


def test_release_during_refresh_closes_parent_and_late_result(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    repository = _Repository()
    first = _Session(notebook_path.parent / "prepared", 11)
    started = threading.Event()

    def blocked(_spec: object, cancelled: Callable[[], bool]) -> _Prepared:
        started.set()
        while not cancelled():
            threading.Event().wait(0.005)
        raise asyncio.CancelledError

    second = _Session(
        notebook_path.parent / "prepared",
        12,
        current={"x": 12},
        capture=blocked,
    )
    registry = PreparedViewRegistry(
        notebook_path,
        repository=cast(ExportRepository, repository),
        connector=cast(Any, _Connector(first, second)),
    )

    async def scenario() -> None:
        selected = await registry.prepare(_request(snapshot))
        original = first.prepared[-1]
        repository.revision += 1
        assert (
            _selected_view(registry, snapshot, poll=True).prepared is selected.prepared
        )
        assert await asyncio.to_thread(started.wait, 2)
        registry.release_binding("browser-client-1234")
        assert original.closed
        await registry.close()
        assert (
            registry.current("dashboard", "browser-client-1234", snapshot.revision)
            is None
        )

    asyncio.run(scenario())


def test_close_waits_for_observation_revision_worker(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(notebook_path)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class GatedRepository(_Repository):
        def observation_revision(self, plan: object) -> int:
            assert cast(Any, plan).producer_sha256 == "a" * 64
            started.set()
            assert release.wait(2)
            assert not self.closed
            finished.set()
            return self.revision

        def close(self) -> None:
            assert finished.is_set()
            super().close()

    repository = GatedRepository()
    monkeypatch.setattr(
        ExportRepository,
        "open",
        classmethod(lambda _cls: cast(ExportRepository, repository)),
    )
    session = _Session(notebook_path.parent / "prepared", 16)
    registry = PreparedViewRegistry(
        notebook_path,
        connector=cast(Any, _Connector(session)),
    )

    async def scenario() -> None:
        selected = await registry.prepare(_request(snapshot))
        repository.revision += 1
        assert (
            _selected_view(registry, snapshot, poll=True).prepared is selected.prepared
        )
        assert await asyncio.to_thread(started.wait, 2)
        closing = asyncio.create_task(registry.close())
        await asyncio.sleep(0.02)
        assert not closing.done()
        assert not repository.closed
        release.set()
        await asyncio.wait_for(closing, 2)

    asyncio.run(scenario())

    assert finished.is_set()
    assert repository.closed
