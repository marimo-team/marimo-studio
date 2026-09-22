"""Expose Marimo code-mode state through a Studio-owned capability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marimo._messaging.notebook.changes import CreateCell, DeleteCell, SetCode
from marimo._messaging.notification import (
    NotebookDocumentTransactionNotification,
    NotificationMessage,
)
from marimo._session.state.session_view import SessionView
from starlette.types import Scope

from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._compat.code_mode import (
    active_notebook,
    attach_code_mode_session,
    code_mode_connection,
)
from marimo_studio._compat.patch import CallbackCloseHandle, ReversiblePatch


def _record_kernel_source(native: Any) -> Any:
    def add_notification(view: SessionView, notification: NotificationMessage) -> None:
        native(view, notification)
        if (
            not isinstance(notification, NotebookDocumentTransactionNotification)
            or notification.transaction.source != "code-mode"
        ):
            return
        # Code mode registers source directly in the kernel before broadcasting
        # this transaction, bypassing the commands SessionView normally records.
        # Like SyncGraphCommand, this is graph-source evidence, not run completion.
        for change in notification.transaction.changes:
            if isinstance(change, (CreateCell, SetCode)):
                view.last_executed_code[change.cell_id] = change.code
            elif isinstance(change, DeleteCell):
                view.last_executed_code.pop(change.cell_id, None)

    return add_notification


_KERNEL_SOURCE_PATCH = ReversiblePatch(
    "code-mode-session-source", SessionView, "add_notification", _record_kernel_source
)


class PrivateCodeModeBridge:
    """Adapt code-mode request state for the tested Marimo layout."""

    def open(self) -> CallbackCloseHandle:
        return _KERNEL_SOURCE_PATCH.open()

    def attach_session(self, scope: Scope, notebook: Path) -> Scope:
        return attach_code_mode_session(scope, notebook)

    def active_notebook(self) -> Path:
        return active_notebook()

    def connection(self) -> StudioServerConnection:
        return code_mode_connection()
