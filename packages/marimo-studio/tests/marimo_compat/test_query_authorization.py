from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from marimo_studio._compat.kernel_values.authorization import (
    authorized_value_arguments,
)
from marimo_studio._compat.kernel_values.authorization_key import (
    initialize_projection_authorization_key,
)
from marimo_studio._compat.kernel_values.query_authorization import (
    authorized_query_arguments,
    verify_query_authorization,
)


def test_query_authorization_is_exact_and_filesystem_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_projection_authorization_key()
    notebook = Path("/workspace/notebook.py")

    def fail_resolve(_path: Path) -> Path:
        raise AssertionError("Query authorization resolved a filesystem path.")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    arguments = authorized_query_arguments(
        query={"region": "emea"},
        fingerprint="fingerprint",
        operation_id="query-1",
        binding_generation=3,
        query_generation=7,
        deadline=9_000_000_000.0,
        session_id="s_123456",
        notebook=notebook,
    )

    assert verify_query_authorization(SimpleNamespace(**arguments), notebook)
    for field, replacement in (
        ("fingerprint", "altered"),
        ("operation_id", "query-2"),
        ("binding_generation", 4),
        ("query_generation", 8),
        ("deadline", 8_000_000_000.0),
        ("session_id", "s_654321"),
    ):
        changed = {**arguments, field: replacement}
        assert not verify_query_authorization(SimpleNamespace(**changed), notebook)

    value_authorization = authorized_value_arguments("revision", (), "preview")[
        "authorization"
    ]
    confused = {**arguments, "authorization": value_authorization}
    assert not verify_query_authorization(SimpleNamespace(**confused), notebook)
