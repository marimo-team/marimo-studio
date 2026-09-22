"""Expose Marimo code-mode state through a Studio-owned capability."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any
from weakref import WeakKeyDictionary

from marimo._messaging.notebook.changes import CreateCell, DeleteCell, SetCode
from marimo._messaging.notification import (
    CellNotification,
    NotebookDocumentTransactionNotification,
    NotificationMessage,
)
from marimo._session.state.session_view import SessionView
from marimo._types.ids import CellId_t
from starlette.types import Scope

from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._compat.code_mode import (
    active_notebook,
    attach_code_mode_session,
    code_mode_connection,
)
from marimo_studio._compat.patch import CallbackCloseHandle, ReversiblePatch


def _record_kernel_source(native: Any) -> Any:
    pending_by_view: WeakKeyDictionary[SessionView, dict[CellId_t, str]] = (
        WeakKeyDictionary()
    )
    lock = Lock()

    def add_notification(view: SessionView, notification: NotificationMessage) -> None:
        native(view, notification)
        with lock:
            pending = pending_by_view.setdefault(view, {})
            if isinstance(notification, NotebookDocumentTransactionNotification):
                for change in notification.transaction.changes:
                    if isinstance(change, (CreateCell, SetCode)):
                        if notification.transaction.source == "code-mode":
                            pending[change.cell_id] = change.code
                        else:
                            pending.pop(change.cell_id, None)
                    elif isinstance(change, DeleteCell):
                        pending.pop(change.cell_id, None)
                        if notification.transaction.source == "code-mode":
                            view.last_executed_code.pop(change.cell_id, None)
            elif (
                isinstance(notification, CellNotification)
                and notification.status == "queued"
                and (code := pending.pop(notification.cell_id, None)) is not None
            ):
                view.last_executed_code[notification.cell_id] = code

            if not pending:
                pending_by_view.pop(view, None)

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
