"""Protect complete Marimo session-cache publication."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import threading
import time
from multiprocessing.connection import Connection
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from marimo._session.state import serialize as native_session_cache
from marimo._session.state.serialize import SessionCacheWriter
from marimo._utils.async_path import AsyncPath

import marimo_studio._compat.server.session_cache as session_cache_module
from marimo_studio._compat.server.session_cache import (
    PrivateSessionCachePublication,
)
from marimo_studio._composition import create_server_adapters
from marimo_studio._filesystem import _secure_operations as secure_operations
from marimo_studio._filesystem.io import read_text
from marimo_studio._filesystem.secure import FileIdentity
from marimo_studio.errors import ConfigurationError


class _ExportingView:
    def __init__(self, marker: str, exports: int) -> None:
        self.marker = marker
        self.exports = exports
        self.generation = 0
        self.writer: SessionCacheWriter | None = None

    def needs_export(self, export_type: str) -> bool:
        assert export_type == "session"
        self.generation += 1
        if self.generation == self.exports:
            assert self.writer is not None
            self.writer.running = False
        return True

    def mark_auto_export_session(self) -> None:
        return


def _writer(
    path: Path, view: _ExportingView, interval: float = 0
) -> SessionCacheWriter:
    writer = SessionCacheWriter(
        session_view=cast(Any, view),
        document=cast(Any, SimpleNamespace(cell_ids=())),
        path=path,
        interval=interval,
        notebook_path=path.with_suffix(".py"),
    )
    view.writer = writer
    writer.running = True
    return writer


def _serialized_view(
    view: _ExportingView,
    **_kwargs: object,
) -> dict[str, object]:
    return {
        "writer": view.marker,
        "generation": view.generation,
        "payload": view.marker * (19 if view.marker == "short" else 16_001),
    }


def _multiprocess_writer(
    path: str,
    marker: str,
    exports: int,
    start: Any,
    ready: Any,
    commit_ready: Any,
    first_commit: Any,
    result: Connection,
) -> None:
    native_session_cache.serialize_session_view = cast(Any, _serialized_view)
    publish = session_cache_module.atomic_write_text
    completed = 0
    commits = 0
    commit_synchronized = False
    rename = secure_operations.os.rename
    replace = secure_operations.os.replace

    def commit(operation: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal commit_synchronized, commits
        if not commit_synchronized:
            commit_ready.set()
            first_commit.wait(timeout=10)
            commit_synchronized = True
        committed = operation(*args, **kwargs)
        commits += 1
        return committed

    def commit_rename(*args: Any, **kwargs: Any) -> Any:
        return commit(rename, *args, **kwargs)

    def commit_replace(*args: Any, **kwargs: Any) -> Any:
        return commit(replace, *args, **kwargs)

    def count_publication(
        path: Path,
        content: str,
        *,
        root: Path | None = None,
    ) -> FileIdentity:
        nonlocal completed
        published = publish(path, content, root=root)
        completed += 1
        return published

    cast(Any, session_cache_module).atomic_write_text = count_publication
    cast(Any, secure_operations.os).rename = commit_rename
    cast(Any, secure_operations.os).replace = commit_replace
    publication = PrivateSessionCachePublication()
    handle = publication.open()
    view = _ExportingView(marker, exports)
    writer = _writer(Path(path), view, interval=0.0005)
    ready.set()
    start.wait()
    try:
        try:
            asyncio.run(writer.run())
        finally:
            handle.close()
        result.send(
            (
                marker,
                view.generation,
                completed,
                commits,
                commit_synchronized,
            )
        )
    finally:
        cast(Any, secure_operations.os).rename = rename
        cast(Any, secure_operations.os).replace = replace
        result.close()


def _assert_complete_snapshot(document: object, exports: int) -> None:
    assert isinstance(document, dict)
    writer = document.get("writer")
    if writer == "initial":
        assert document == {"writer": "initial"}
        return
    assert writer in {"short", "long"}
    assert document.get("payload") == writer * (19 if writer == "short" else 16_001)
    generation = document.get("generation")
    assert isinstance(generation, int)
    assert 1 <= generation <= exports


@pytest.mark.native_process
def test_session_cache_multi_process_writers_publish_complete_json(
    tmp_path: Path,
) -> None:
    exports = 80
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"writer": "initial"}), encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    ready = (context.Event(), context.Event())
    commit_ready = (context.Event(), context.Event())
    first_commit = context.Barrier(3)
    pipes = (context.Pipe(duplex=False), context.Pipe(duplex=False))
    receivers = tuple(pipe[0] for pipe in pipes)
    senders = tuple(pipe[1] for pipe in pipes)
    processes = [
        context.Process(
            target=_multiprocess_writer,
            args=(
                str(path),
                marker,
                exports,
                start,
                ready[index],
                commit_ready[index],
                first_commit,
                senders[index],
            ),
        )
        for index, marker in enumerate(("short", "long"))
    ]
    for process in processes:
        process.start()
    for sender in senders:
        sender.close()
    results: list[tuple[str, int, int, int, bool]] = []
    try:
        assert all(event.wait(timeout=10) for event in ready)
        start.set()
        reads = 0
        failures: list[str] = []
        deadline = time.monotonic() + 20
        while not all(event.is_set() for event in commit_ready):
            if time.monotonic() >= deadline:
                pytest.fail("session-cache writers did not reach the commit barrier")
            document = json.loads(read_text(path))
            _assert_complete_snapshot(document, exports)
            reads += 1
        document = json.loads(read_text(path))
        assert document == {"writer": "initial"}
        reads += 1
        first_commit.wait(timeout=10)
        while any(process.is_alive() for process in processes):
            if time.monotonic() >= deadline:
                pytest.fail("session-cache writer processes did not finish")
            try:
                document = json.loads(read_text(path))
                _assert_complete_snapshot(document, exports)
            except (AssertionError, json.JSONDecodeError) as error:
                failures.append(str(error))
                break
            except ConfigurationError:
                continue
            reads += 1
    finally:
        start.set()
        first_commit.abort()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        for receiver in receivers:
            if receiver.poll(timeout=1):
                results.append(cast(tuple[str, int, int, int, bool], receiver.recv()))
            receiver.close()
    assert reads > 0
    assert failures == []
    assert [process.exitcode for process in processes] == [0, 0]
    assert {
        marker: (generation, completed, commits, synchronized)
        for marker, generation, completed, commits, synchronized in results
    } == {
        "short": (exports, exports, exports, True),
        "long": (exports, exports, exports, True),
    }
    final = json.loads(read_text(path))
    _assert_complete_snapshot(final, exports)
    assert final["writer"] in {"short", "long"}
    assert {item.name for item in tmp_path.iterdir()} == {"session.json"}


def test_session_cache_preserves_export_order_interval_and_error_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "session.json"
    events: list[object] = []

    class View(_ExportingView):
        def mark_auto_export_session(self) -> None:
            events.append("marked")

    view = View("short", 2)
    writer = _writer(path, view, interval=0.125)

    def serialize(view: View, **_kwargs: object) -> dict[str, object]:
        events.append(("serialized", view.generation))
        return {"generation": view.generation}

    def publish(destination: Path, content: str) -> object:
        events.append(("published", json.loads(content)["generation"]))
        if view.generation == 2:
            raise OSError("disk stopped")
        destination.write_text(content, encoding="utf-8")
        return object()

    async def sleep(interval: float) -> None:
        events.append(("slept", interval))

    monkeypatch.setattr(native_session_cache, "serialize_session_view", serialize)
    monkeypatch.setattr(session_cache_module, "atomic_write_text", publish)
    monkeypatch.setattr(session_cache_module.asyncio, "sleep", sleep)
    caplog.set_level("ERROR", logger="marimo")
    handle = PrivateSessionCachePublication().open()
    try:
        asyncio.run(writer.run())
    finally:
        handle.close()

    assert events == [
        "marked",
        ("serialized", 1),
        ("published", 1),
        ("slept", 0.125),
        "marked",
        ("serialized", 2),
        ("published", 2),
    ]
    assert "Write error: disk stopped" in caplog.text


def test_session_cache_cancellation_waits_for_async_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"writer": "published"}), encoding="utf-8")
    view = _ExportingView("short", 1)
    writer = _writer(path, view)
    writer.path = AsyncPath(path)
    rename = secure_operations.os.rename
    replace = secure_operations.os.replace

    def commit(operation: Any, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("session-cache publication was not released")
        committed = operation(*args, **kwargs)
        finished.set()
        return committed

    def commit_rename(*args: Any, **kwargs: Any) -> Any:
        return commit(rename, *args, **kwargs)

    def commit_replace(*args: Any, **kwargs: Any) -> Any:
        return commit(replace, *args, **kwargs)

    monkeypatch.setattr(
        native_session_cache, "serialize_session_view", _serialized_view
    )
    monkeypatch.setattr(secure_operations.os, "rename", commit_rename)
    monkeypatch.setattr(secure_operations.os, "replace", commit_replace)
    handle = PrivateSessionCachePublication().open()

    async def cancel() -> None:
        writer.start()
        assert await asyncio.to_thread(entered.wait, 10)
        assert json.loads(read_text(path)) == {"writer": "published"}
        assert len(tuple(tmp_path.iterdir())) == 2
        assert writer.task is not None
        writer.task.cancel()
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not writer.task.done()
            assert not finished.is_set()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await writer.task
        assert writer.running is False
        assert finished.is_set()
        assert json.loads(read_text(path))["writer"] == "short"
        assert {item.name for item in tmp_path.iterdir()} == {"session.json"}

    try:
        asyncio.run(cancel())
    finally:
        release.set()
        handle.close()


def test_session_cache_path_writer_keeps_synchronous_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "session.json"
    calls: list[Path] = []
    view = _ExportingView("short", 1)
    writer = _writer(path, view)
    writer.path = path

    def publish(destination: Path, content: str) -> object:
        calls.append(destination)
        destination.write_text(content, encoding="utf-8")
        return object()

    monkeypatch.setattr(
        native_session_cache, "serialize_session_view", _serialized_view
    )
    monkeypatch.setattr(session_cache_module, "atomic_write_text", publish)
    handle = PrivateSessionCachePublication().open()
    try:
        asyncio.run(writer.run())
    finally:
        handle.close()

    assert calls == [path]
    assert json.loads(read_text(path))["writer"] == "short"


def test_session_cache_reports_failure_before_propagating_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"writer": "published"}), encoding="utf-8")
    view = _ExportingView("short", 1)
    writer = _writer(path, view)
    writer.path = AsyncPath(path)

    def reject_replace(*_args: object, **_kwargs: object) -> None:
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("session-cache publication was not released")
        finished.set()
        raise OSError("replace unavailable")

    monkeypatch.setattr(
        native_session_cache, "serialize_session_view", _serialized_view
    )
    monkeypatch.setattr(secure_operations.os, "rename", reject_replace)
    monkeypatch.setattr(secure_operations.os, "replace", reject_replace)
    caplog.set_level("ERROR", logger="marimo")
    handle = PrivateSessionCachePublication().open()

    async def cancel() -> None:
        writer.start()
        assert await asyncio.to_thread(entered.wait, 10)
        assert json.loads(read_text(path)) == {"writer": "published"}
        assert len(tuple(tmp_path.iterdir())) == 2
        assert writer.task is not None
        writer.task.cancel()
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not writer.task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await writer.task
        assert writer.task.cancelled()
        assert writer.running is False
        assert finished.is_set()

    try:
        asyncio.run(cancel())
    finally:
        release.set()
        handle.close()

    assert json.loads(read_text(path)) == {"writer": "published"}
    assert {item.name for item in tmp_path.iterdir()} == {"session.json"}
    assert "Write error: Could not replace mutable workspace file" in caplog.text


def test_server_composition_reference_counts_and_restores_session_cache_patch() -> None:
    original = SessionCacheWriter.run
    first = create_server_adapters().lifecycle.open()
    replacement = SessionCacheWriter.run
    second = create_server_adapters().lifecycle.open()
    try:
        assert replacement is not original
        first.close()
        assert SessionCacheWriter.run is replacement
        second.close()
        assert SessionCacheWriter.run is original
    finally:
        first.close()
        second.close()
