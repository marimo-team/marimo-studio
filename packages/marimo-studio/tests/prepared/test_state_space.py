from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._prepared.state_space import (
    load_state_space_source,
)
from marimo_studio.errors import PublicationError

_EXAMPLES = Path(__file__).resolve().parents[4] / "examples" / "__marimo__" / "studio"


def test_state_space_source_uses_the_view_states_file(tmp_path: Path) -> None:
    source = load_state_space_source(tmp_path)

    assert source.path == tmp_path / "states.yaml"
    assert source.state_space is None


def test_state_space_expands_a_deterministic_cartesian_matrix(tmp_path: Path) -> None:
    tmp_path.joinpath("states.yaml").write_text(
        """schema: marimo-export.states.v1
default_state: baseline
states:
  baseline:
    metric: CO2
    threshold: 0.5
matrix:
  threshold: [0.1, 0.2]
  metric: [CO2, Light]
""",
        encoding="utf-8",
    )

    source = load_state_space_source(tmp_path)

    assert source.state_space is not None
    assert source.state_space.default_state == "baseline"
    assert source.state_space.states == {
        "baseline": {"metric": "CO2", "threshold": 0.5},
        "matrix-000000": {"metric": "CO2", "threshold": 0.1},
        "matrix-000001": {"metric": "CO2", "threshold": 0.2},
        "matrix-000002": {"metric": "Light", "threshold": 0.1},
        "matrix-000003": {"metric": "Light", "threshold": 0.2},
    }


def test_state_space_source_rejects_changed_input_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "states.yaml"
    path.write_text(
        """schema: marimo-export.states.v1
default_state: baseline
states:
  baseline: {mode: first}
""",
        encoding="utf-8",
    )
    source = load_state_space_source(tmp_path)
    path.write_text(
        """schema: marimo-export.states.v1
default_state: baseline
states:
  baseline: {mode: second}
""",
        encoding="utf-8",
    )

    with pytest.raises(PublicationError, match="changed while it was used"):
        source.require_current()


def test_state_space_source_digest_tracks_equivalent_file_edits(
    tmp_path: Path,
) -> None:
    path = tmp_path / "states.yaml"
    path.write_text(
        """schema: marimo-export.states.v1
default_state: baseline
states:
  baseline: {mode: first}
""",
        encoding="utf-8",
    )
    source = load_state_space_source(tmp_path)
    path.write_text(
        """schema: marimo-export.states.v1
default_state: baseline
states:
  baseline:
    mode: first
""",
        encoding="utf-8",
    )
    current = load_state_space_source(tmp_path)

    assert source.state_space is not None
    assert current.state_space is not None
    assert source.state_space.digest == current.state_space.digest
    assert source.digest != current.digest
    with pytest.raises(PublicationError, match="changed while it was used"):
        source.require_current()


@pytest.mark.parametrize(
    "content, message",
    [
        ("schema: wrong\ndefault_state: baseline\nstates: {baseline: {}}\n", "schema"),
        (
            "schema: marimo-export.states.v1\ndefault_state: baseline\nextra: true\n",
            "does not accept",
        ),
        (
            "schema: marimo-export.states.v1\ndefault_state: baseline\n"
            "states: {baseline: {}}\nstates: {other: {}}\n",
            "duplicate",
        ),
        (
            "schema: marimo-export.states.v1\ndefault_state: baseline\n"
            "matrix: {mode: []}\n",
            "at least one value",
        ),
        (
            "schema: marimo-export.states.v1\ndefault_state: matrix-000000\n"
            "matrix: {mode: [first, first]}\n",
            "duplicate values",
        ),
        (
            "schema: marimo-export.states.v1\ndefault_state: baseline\n"
            "states: {baseline: {when: 2026-09-02}}\n",
            "JSON-compatible",
        ),
    ],
)
def test_state_space_rejects_invalid_contracts(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    tmp_path.joinpath("states.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(PublicationError, match=message):
        load_state_space_source(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "athletes/field",
        "athletes/overview",
        "earthquakes/operations",
        "occupancy/monitor",
        "occupancy/model-review",
        "occupancy/pdf-report",
    ],
)
def test_example_views_provide_valid_state_spaces(relative: str) -> None:
    source = load_state_space_source(_EXAMPLES / relative)
    assert source.state_space is not None
