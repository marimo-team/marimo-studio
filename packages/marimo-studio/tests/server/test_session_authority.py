from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.requests import Request

from marimo_studio._server.ports import SessionOwner
from marimo_studio._server.presentation.capability import parse_presentation_capability
from marimo_studio._server.presentation.session import (
    PresentationSession,
    assign_presentation_session,
    presentation_session_redirect,
    valid_presentation_replay,
)
from marimo_studio._server.presentation.session_ids import SessionIdAllocator
from marimo_studio._server.records import ServerContext


def _assignment_context(mode: Literal["edit", "run"] = "run") -> ServerContext:
    return cast(
        ServerContext,
        SimpleNamespace(
            base_url="",
            file_key="notebook.py",
            mode=mode,
            notebook=Path("/workspace/notebook.py"),
            server_token="server-token",
        ),
    )


def _assignment_request(query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/dashboard/",
            "raw_path": b"/dashboard/",
            "query_string": query.removeprefix("?").encode(),
            "headers": [],
            "client": ("test", 123),
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize(
    ("query", "mode", "preserve", "exists", "matches", "expected"),
    (
        pytest.param(
            "session_id=s_native&marimo_studio_resume=1&region=emea",
            "run",
            True,
            True,
            True,
            True,
            id="current",
        ),
        pytest.param(
            "session_id=s_other1&marimo_studio_resume=1&region=emea",
            "run",
            True,
            True,
            True,
            False,
            id="runtime-tampered",
        ),
        pytest.param(
            "session_id=s_native&marimo_studio_resume=1&marimo_studio_resume=1",
            "run",
            True,
            True,
            True,
            False,
            id="marker-duplicated",
        ),
        pytest.param(
            "session_id=s_native&marimo_studio_resume=1",
            "run",
            True,
            False,
            True,
            False,
            id="session-closed",
        ),
        pytest.param(
            "session_id=s_native&marimo_studio_resume=1&region=apac",
            "run",
            True,
            True,
            False,
            False,
            id="query-changed",
        ),
        pytest.param(
            "session_id=s_native&marimo_studio_resume=1",
            "run",
            False,
            True,
            True,
            False,
            id="preservation-disabled",
        ),
        pytest.param(
            "session_id=s_native&marimo_studio_resume=1",
            "edit",
            True,
            True,
            True,
            False,
            id="edit-mode",
        ),
    ),
)
def test_stored_renewal_replay_requires_current_session_authority(
    query: str,
    mode: Literal["edit", "run"],
    preserve: bool,
    exists: bool,
    matches: bool,
    expected: bool,
) -> None:
    sessions = cast(
        Any,
        SimpleNamespace(
            is_session_id=lambda value: value == "s_native",
            exists=lambda _context, _session_id: exists,
            matches_creation_query=lambda _context, _session_id, _query: matches,
        ),
    )

    valid = valid_presentation_replay(
        _assignment_request(query),
        _assignment_context(mode),
        PresentationSession("s_view01", "s_native", "signed-renewal"),
        sessions,
        preserve_session=preserve,
    )

    assert valid is expected


def test_presentation_assignment_mints_a_signed_fresh_pair() -> None:
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, _session_id: "unclaimed",
        ),
    )

    assigned = assign_presentation_session(
        _assignment_request(),
        _assignment_context(),
        "dashboard",
        sessions,
        SessionIdAllocator(key=b"test-key", start=0),
        preserve_session=False,
    )
    capability = parse_presentation_capability(assigned.renewal_token)

    assert assigned.session_id != assigned.runtime_session_id
    assert capability is not None
    assert capability.session_id == assigned.session_id
    assert capability.runtime_session_id == assigned.runtime_session_id


def test_session_pair_skips_registered_and_sibling_id_collisions() -> None:
    context = _assignment_context()
    available = cast(
        Any,
        SimpleNamespace(ownership=lambda _context, _session_id: "unclaimed"),
    )
    expected = SessionIdAllocator(key=b"test-key", start=0).allocate_pair(
        context,
        available,
    )
    sessions = SimpleNamespace(
        ownership=lambda _context, session_id: (
            "current" if session_id == expected[1] else "unclaimed"
        ),
    )
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    pair = session_ids.allocate_pair(context, cast(Any, sessions))

    assert pair[0] == expected[0]
    assert pair[1] not in {expected[0], expected[1]}


def test_abandoned_public_redirects_do_not_exhaust_session_allocation() -> None:
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, _session_id: "unclaimed",
            is_session_id=lambda value: isinstance(value, str),
        ),
    )
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    identities: set[tuple[str, str | None]] = set()

    for _request in range(1_100):
        response = presentation_session_redirect(
            _assignment_request(),
            _assignment_context(),
            "dashboard",
            sessions,
            session_ids,
            preserve_session=False,
        )
        query = parse_qs(urlsplit(response.headers["location"]).query)
        capability = parse_presentation_capability(query["marimo_studio_renewal"][0])
        assert capability is not None
        identities.add((capability.session_id, capability.runtime_session_id))

    assert len(identities) == 1_100


def test_observed_ids_do_not_reveal_an_allocatable_next_window() -> None:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    available = cast(
        Any,
        SimpleNamespace(ownership=lambda _context, _session_id: "unclaimed"),
    )
    observed = session_ids.allocate_pair(_assignment_context(), available)
    value = 0
    for character in observed[1].removeprefix("s_"):
        value = value * len(alphabet) + alphabet.index(character)

    def encode(candidate: int) -> str:
        characters = [alphabet[0]] * 6
        for index in range(5, -1, -1):
            candidate, remainder = divmod(candidate, len(alphabet))
            characters[index] = alphabet[remainder]
        return "s_" + "".join(characters)

    preclaimed = {
        encode((value + offset) % (len(alphabet) ** 6)) for offset in range(1, 33)
    }
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, session_id: (
                "current" if session_id in preclaimed else "unclaimed"
            ),
        ),
    )

    allocated = session_ids.allocate_pair(_assignment_context(), sessions)

    assert not set(allocated) & preclaimed


def test_concurrent_session_pair_allocations_are_globally_unique() -> None:
    sessions = cast(
        Any,
        SimpleNamespace(ownership=lambda _context, _session_id: "unclaimed"),
    )
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        allocated = tuple(
            pool.map(
                lambda _index: session_ids.allocate_pair(
                    _assignment_context(),
                    sessions,
                ),
                range(2),
            )
        )

    issued = {session_id for pair in allocated for session_id in pair}
    assert len(issued) == 4
    assert all(presentation != runtime for presentation, runtime in allocated)
    assert allocated[0] != allocated[1]


def test_failed_pair_allocation_leaves_the_allocator_usable() -> None:
    blocked = True
    probes = 0

    def exists(_context: object, _session_id: str) -> bool:
        nonlocal probes
        probes += 1
        return blocked and probes > 1

    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda context, session_id: (
                "current" if exists(context, session_id) else "unclaimed"
            )
        ),
    )
    session_ids = SessionIdAllocator(key=b"test-key", start=0)

    with pytest.raises(RuntimeError, match="distinct Studio session ID"):
        session_ids.allocate_pair(_assignment_context(), sessions)
    blocked = False
    pair = session_ids.allocate_pair(_assignment_context(), sessions)

    assert pair[0] != pair[1]


def test_admitted_runtime_survives_ttl_and_inactive_capacity_pressure() -> None:
    now = [0.0]
    claimed: set[str] = set()
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, session_id: (
                "current" if session_id in claimed else "unclaimed"
            ),
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(
        key=b"test-key",
        start=0,
        clock=lambda: now[0],
        authority_ttl_seconds=1,
        max_authorities=2,
    )
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
    )
    claimed.add(runtime_session_id)
    now[0] = 2
    for view_name in ("first", "second", "third"):
        session_ids.assign_pair(context, sessions, view_name)

    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=False,
    )


def test_admitted_runtime_authority_spans_configured_view_documents() -> None:
    claimed: set[str] = set()
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, session_id: (
                "current" if session_id in claimed else "unclaimed"
            ),
            owner=lambda _context, session_id: SessionOwner(
                "current" if session_id in claimed else "unclaimed",
                object() if session_id in claimed else None,
            ),
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
    )
    claimed.add(runtime_session_id)
    session_ids.settle_admission(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
    )

    assert session_ids.allows(
        context,
        sessions,
        "executive",
        presentation_session_id,
        runtime_session_id,
    )
    assert session_ids.authorize(
        context,
        sessions,
        "executive",
        presentation_session_id,
        runtime_session_id,
        native_admission=False,
    )


def test_closed_admitted_runtime_releases_authority_capacity() -> None:
    now = [0.0]
    claimed: set[str] = set()
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, session_id: (
                "current" if session_id in claimed else "unclaimed"
            ),
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(
        key=b"test-key",
        start=0,
        clock=lambda: now[0],
        authority_ttl_seconds=1,
        max_authorities=1,
    )
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
    )
    claimed.add(runtime_session_id)
    now[0] = 2
    claimed.remove(runtime_session_id)

    replacement = session_ids.assign_pair(context, sessions, "replacement")

    assert replacement[0] != replacement[1]


def test_aborted_native_admissions_do_not_exhaust_authority_capacity() -> None:
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, _session_id: "unclaimed",
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(
        key=b"test-key",
        start=0,
        max_authorities=2,
    )
    for index in range(5):
        presentation_session_id, runtime_session_id = session_ids.assign_pair(
            context,
            sessions,
            f"view-{index}",
        )
        assert session_ids.authorize(
            context,
            sessions,
            f"view-{index}",
            presentation_session_id,
            runtime_session_id,
            native_admission=True,
        )
        session_ids.settle_admission(
            context,
            sessions,
            f"view-{index}",
            presentation_session_id,
            runtime_session_id,
        )

    replacement = session_ids.assign_pair(context, sessions, "replacement")

    assert replacement[0] != replacement[1]


def test_pending_native_admission_survives_capacity_pressure_until_claimed() -> None:
    now = [0.0]
    claimed: set[str] = set()
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, session_id: (
                "current" if session_id in claimed else "unclaimed"
            ),
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(
        key=b"test-key",
        start=0,
        clock=lambda: now[0],
        authority_ttl_seconds=1,
        max_authorities=2,
    )
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
    )
    session_ids.assign_pair(context, sessions, "first")
    session_ids.assign_pair(context, sessions, "second")
    claimed.add(runtime_session_id)
    now[0] = 2
    session_ids.assign_pair(context, sessions, "third")

    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=False,
    )


def test_config_during_native_admission_preserves_owner_phase() -> None:
    claimed: set[str] = set()
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, session_id: (
                "current" if session_id in claimed else "unclaimed"
            ),
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=False,
    )
    claimed.add(runtime_session_id)
    session_ids.settle_admission(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
    )

    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=False,
    )


def test_concurrent_native_admission_accepts_one_owner() -> None:
    sessions = cast(
        Any,
        SimpleNamespace(ownership=lambda _context, _session_id: "unclaimed"),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    barrier = Barrier(2)

    def admit() -> bool:
        barrier.wait()
        return session_ids.authorize(
            context,
            sessions,
            "dashboard",
            presentation_session_id,
            runtime_session_id,
            native_admission=True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = tuple(pool.map(lambda _index: admit(), range(2)))

    assert sorted(admitted) == [False, True]
    session_ids.settle_admission(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
    )


def test_authorize_rejects_ownership_changed_after_snapshot() -> None:
    claim = object()
    state = [SessionOwner("unclaimed", None)]
    sessions = cast(
        Any,
        SimpleNamespace(
            owner=lambda _context, _session_id: state[0],
            ownership=lambda _context, _session_id: state[0].state,
        ),
    )
    context = _assignment_context()
    session_ids = SessionIdAllocator(key=b"test-key", start=0)
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )
    snapshot = state[0]
    state[0] = SessionOwner("current", claim)

    assert not session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=True,
        expected_owner=snapshot,
    )


def test_authority_key_uses_the_gateway_canonical_notebook_without_resolving() -> None:
    class CanonicalNotebook:
        def __str__(self) -> str:
            return "/workspace/notebook.py"

        def resolve(self) -> None:
            raise AssertionError("canonical notebook paths must not be resolved here")

    context = cast(
        ServerContext,
        SimpleNamespace(
            base_url="",
            file_key="notebook.py",
            mode="run",
            notebook=CanonicalNotebook(),
        ),
    )
    sessions = cast(
        Any,
        SimpleNamespace(
            ownership=lambda _context, _session_id: "unclaimed",
        ),
    )
    session_ids = SessionIdAllocator(key=b"test-key", start=0)

    pair = session_ids.assign_pair(context, sessions, "dashboard")

    assert pair[0] != pair[1]


def test_session_ownership_checks_run_outside_allocator_lock() -> None:
    session_ids = SessionIdAllocator(key=b"test-key", start=0)

    def ownership(_context: object, _session_id: str) -> str:
        is_owned = cast(Any, session_ids._lock)._is_owned
        assert not is_owned()
        return "unclaimed"

    sessions = cast(Any, SimpleNamespace(ownership=ownership))
    context = _assignment_context()
    presentation_session_id, runtime_session_id = session_ids.assign_pair(
        context,
        sessions,
        "dashboard",
    )

    assert session_ids.allows(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
    )
    assert session_ids.authorize(
        context,
        sessions,
        "dashboard",
        presentation_session_id,
        runtime_session_id,
        native_admission=False,
    )
