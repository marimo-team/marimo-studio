"""Keep kernel-authored source in the native session's runtime evidence."""

import pytest
from marimo._ast.cell import CellConfig
from marimo._messaging.notebook.changes import (
    CreateCell,
    DeleteCell,
    SetCode,
    Transaction,
    TransactionSource,
)
from marimo._messaging.notification import (
    CellNotification,
    NotebookDocumentTransactionNotification,
)
from marimo._messaging.serde import serialize_kernel_message
from marimo._runtime.commands import ExecuteCellsCommand
from marimo._session.state.session_view import SessionView
from marimo._types.ids import CellId_t

from marimo_studio._composition import create_server_adapters


def _transaction(source: TransactionSource) -> NotebookDocumentTransactionNotification:
    existing, created, deleted = map(CellId_t, ("existing", "created", "deleted"))
    return NotebookDocumentTransactionNotification(
        transaction=Transaction(
            source=source,
            changes=(
                SetCode(existing, "value = 2"),
                CreateCell(created, "result = value + 1", "_", CellConfig()),
                DeleteCell(deleted),
            ),
        )
    )


def _view() -> SessionView:
    view = SessionView()
    view.add_control_request(
        ExecuteCellsCommand(
            cell_ids=[CellId_t("existing"), CellId_t("deleted")],
            codes=["value = 1", "obsolete = 1"],
        )
    )
    return view


def test_code_mode_source_waits_until_each_cell_is_queued() -> None:
    view = _view()
    existing, created = map(CellId_t, ("existing", "created"))
    handle = create_server_adapters().lifecycle.open()
    try:
        view.add_raw_notification(serialize_kernel_message(_transaction("code-mode")))
        assert view.last_executed_code == {existing: "value = 1"}

        view.add_notification(CellNotification(existing, status="queued"))
        assert view.last_executed_code == {existing: "value = 2"}

        view.add_notification(CellNotification(created, status="queued"))
        assert view.last_executed_code == {
            existing: "value = 2",
            created: "result = value + 1",
        }
    finally:
        handle.close()


@pytest.mark.parametrize("source", ["frontend", "file-watch"])
def test_other_document_transactions_supersede_pending_code_mode_source(
    source: TransactionSource,
) -> None:
    view = _view()
    existing = CellId_t("existing")
    handle = create_server_adapters().lifecycle.open()
    try:
        view.add_raw_notification(serialize_kernel_message(_transaction("code-mode")))
        view.add_raw_notification(
            serialize_kernel_message(
                NotebookDocumentTransactionNotification(
                    transaction=Transaction(
                        source=source,
                        changes=(SetCode(existing, "value = 3"),),
                    )
                )
            )
        )
        view.add_notification(CellNotification(existing, status="queued"))
        assert view.last_executed_code[existing] == "value = 1"
    finally:
        handle.close()


def test_code_mode_evidence_patch_is_reversible() -> None:
    view = _view()
    existing = CellId_t("existing")
    handle = create_server_adapters().lifecycle.open()
    view.add_raw_notification(serialize_kernel_message(_transaction("code-mode")))
    handle.close()
    view.add_notification(CellNotification(existing, status="queued"))
    assert view.last_executed_code[existing] == "value = 1"
