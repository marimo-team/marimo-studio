"""Protect the public semantic cell identity."""

from __future__ import annotations

import pytest

from marimo_studio import CellRef


def test_cell_ref_round_trips_full_digest_and_occurrence() -> None:
    digest = "a" * 64
    layout_digest = "b" * 64
    ref = CellRef(digest.upper(), layout_digest.upper(), 3)

    assert ref.fingerprint == digest
    assert ref.layout_fingerprint == layout_digest
    assert str(ref) == f"cell:v1:{digest}:{layout_digest}:3"
    assert CellRef.parse(str(ref)) == ref


def test_cell_ref_rejects_inexact_identity() -> None:
    for value in (
        "cell:v1:short:short:0",
        f"cell:v1:{'a' * 64}:short:0",
        f"cell:v1:{'z' * 64}:{'a' * 64}:0",
        f"cell:v1:{'a' * 64}:{'b' * 64}:-1",
    ):
        with pytest.raises(ValueError):
            CellRef.parse(value)
