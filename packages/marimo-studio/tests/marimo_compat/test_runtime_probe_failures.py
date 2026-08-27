from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import marimo_studio._compat.kernel_values.session as kernel_session_module
import marimo_studio._compat.runtime_probe as runtime_probe_module
from marimo_studio._compat.kernel_values.session import _FunctionResultWaiter
from marimo_studio._compat.runtime_probe import probe_runtime
from marimo_studio._server.presentation.ports import ProjectionUnavailable


def test_runtime_probe_preserves_session_creation_failures(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingManager:
        shutdown_called = False

        @staticmethod
        def create_session(*_: object, **__: object) -> object:
            raise RuntimeError("session startup failed")

        def shutdown(self) -> None:
            self.shutdown_called = True

    manager = FailingManager()
    monkeypatch.setattr(
        runtime_probe_module,
        "_build_manager",
        lambda *_args, **_kwargs: manager,
    )

    with pytest.raises(RuntimeError, match="session startup failed"):
        asyncio.run(
            probe_runtime(
                notebook_path,
                cell_ids=(),
                variables=(),
            )
        )

    assert manager.shutdown_called


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
