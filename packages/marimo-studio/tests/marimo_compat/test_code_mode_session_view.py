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
from marimo._messaging.notification import NotebookDocumentTransactionNotification
from marimo._messaging.serde import serialize_kernel_message
from marimo._runtime.commands import ExecuteCellsCommand
from marimo._session.state.session_view import SessionView
from marimo._types.ids import CellId_t

from marimo_studio._composition import create_server_adapters


@pytest.mark.parametrize("source", ["code-mode", "frontend", "file-watch"])
def test_kernel_source_evidence_follows_code_mode_transactions(
    source: TransactionSource,
) -> None:
    view = SessionView()
    existing, created, deleted = map(CellId_t, ("existing", "created", "deleted"))
    view.add_control_request(
        ExecuteCellsCommand(
            cell_ids=[existing, deleted],
            codes=["value = 1", "obsolete = 1"],
        )
    )
    original = view.last_executed_code.copy()
    handle = create_server_adapters().lifecycle.open()
    try:
        view.add_raw_notification(
            serialize_kernel_message(
                NotebookDocumentTransactionNotification(
                    transaction=Transaction(
                        source=source,
                        changes=(
                            SetCode(existing, "value = 2"),
                            CreateCell(
                                created, "result = value + 1", "_", CellConfig()
                            ),
                            DeleteCell(deleted),
                        ),
                    )
                )
            )
        )
        assert view.last_executed_code == (
            {existing: "value = 2", created: "result = value + 1"}
            if source == "code-mode"
            else original
        )
        view.add_control_request(
            ExecuteCellsCommand(cell_ids=[existing], codes=["value = 3"])
        )
        assert view.last_executed_code[existing] == "value = 3"
    finally:
        handle.close()

    view.add_notification(
        NotebookDocumentTransactionNotification(
            transaction=Transaction(
                source="code-mode", changes=(SetCode(existing, "value = 4"),)
            )
        )
    )
    assert view.last_executed_code[existing] == "value = 3"
