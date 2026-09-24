from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import marimo_studio._compat.kernel_values.session as kernel_session_module
import marimo_studio._compat.runtime_probe as runtime_probe_module
from marimo_studio._compat.kernel_values.session import _FunctionResultWaiter
from marimo_studio._compat.runtime_probe import probe_runtime_in_worker
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio.errors import RuntimeTimeoutError


def test_runtime_probe_preserves_session_creation_failures(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingManager:
        shutdown_called = False

        @staticmethod
        async def create_session(*_: object, **__: object) -> object:
            raise RuntimeError("session startup failed")

        @staticmethod
        def get_session(_session_id: object) -> None:
            return None

        async def shutdown(self) -> None:
            self.shutdown_called = True

    manager = FailingManager()
    monkeypatch.setattr(
        runtime_probe_module,
        "_build_manager",
        lambda *_args, **_kwargs: manager,
    )

    with pytest.raises(RuntimeError, match="session startup failed"):
        asyncio.run(
            probe_runtime_in_worker(
                notebook_path,
                cell_ids=(),
                variables=(),
            )
        )

    assert manager.shutdown_called


def test_runtime_probe_stops_a_session_launched_past_its_startup_timeout(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._session.types import KernelState

    events: list[object] = []

    class StoppingSession:
        closed = False
        polls_after_close = 0

        def kernel_state(self) -> KernelState:
            if not self.closed:
                return KernelState.RUNNING
            self.polls_after_close += 1
            # The kernel thread reports STOPPED a few polls after close.
            return (
                KernelState.STOPPED
                if self.polls_after_close > 3
                else KernelState.RUNNING
            )

    session = StoppingSession()

    class StalledManager:
        def __init__(self) -> None:
            self.sessions: dict[object, StoppingSession] = {}

        async def create_session(self, session_id: object, *_: object, **__: object):
            # Marimo's shielded launch registers the session while the waiter
            # is still blocked, so the waiter times out without a result.
            self.sessions[session_id] = session
            await asyncio.Event().wait()

        def get_session(self, session_id: object) -> StoppingSession | None:
            return self.sessions.get(session_id)

        def close_session(self, session_id: object) -> None:
            events.append("close")
            self.sessions.pop(session_id).closed = True

        async def shutdown(self) -> None:
            events.append(("shutdown", session.kernel_state()))

    monkeypatch.setattr(
        runtime_probe_module,
        "_build_manager",
        lambda *_args, **_kwargs: StalledManager(),
    )

    with pytest.raises(RuntimeTimeoutError, match="did not start within"):
        asyncio.run(
            probe_runtime_in_worker(
                notebook_path,
                cell_ids=(),
                variables=(),
                timeout=0.05,
            )
        )

    assert events == ["close", ("shutdown", KernelState.STOPPED)]


def test_value_waiter_surfaces_an_invalid_kernel_response() -> None:
    from marimo._messaging.notification import (
        FunctionCallResultNotification,
        HumanReadableStatus,
    )
    from marimo._messaging.serde import serialize_kernel_message
    from marimo._types.ids import RequestId

    async def receive() -> None:
        loop = asyncio.get_running_loop()
        waiter = _FunctionResultWaiter(
            "call",
            loop,
            kernel_session_module._ProjectionWorkLease(
                kernel_session_module._SessionProjectionWork()
            ),
        )
        waiter.on_notification_sent(
            None,
            serialize_kernel_message(
                FunctionCallResultNotification(
                    function_call_id=RequestId("call"),
                    return_value={"values": []},
                    status=HumanReadableStatus(code="ok"),
                    found=True,
                )
            ),
        )
        with pytest.raises(ProjectionUnavailable) as raised:
            await waiter.future
        assert raised.value.code == "invalid-value-response"

    asyncio.run(receive())
