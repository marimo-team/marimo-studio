from __future__ import annotations

from pathlib import Path

import pytest
from marimo_export.spec import STATE_SPACE_SCHEMA

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
        f"""schema: {STATE_SPACE_SCHEMA}
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


def test_state_space_digest_tracks_semantics_and_source_stability(
    tmp_path: Path,
) -> None:
    path = tmp_path / "states.yaml"
    path.write_text(
        f"""schema: {STATE_SPACE_SCHEMA}
default_state: baseline
states:
  baseline: {{mode: first}}
""",
        encoding="utf-8",
    )
    source = load_state_space_source(tmp_path)
    path.write_text(
        f"""schema: {STATE_SPACE_SCHEMA}
default_state: baseline
states:
  baseline: {{mode: second}}
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
        f"""schema: {STATE_SPACE_SCHEMA}
default_state: baseline
states:
  baseline: {{mode: first}}
""",
        encoding="utf-8",
    )
    source = load_state_space_source(tmp_path)
    path.write_text(
        f"""schema: {STATE_SPACE_SCHEMA}
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
            f"schema: {STATE_SPACE_SCHEMA}\ndefault_state: baseline\nextra: true\n",
            "does not accept",
        ),
        (
            f"schema: {STATE_SPACE_SCHEMA}\ndefault_state: baseline\n"
            "states: {baseline: {}}\nstates: {other: {}}\n",
            "duplicate",
        ),
        (
            f"schema: {STATE_SPACE_SCHEMA}\ndefault_state: baseline\n"
            "matrix: {mode: []}\n",
            "at least one value",
        ),
        (
            f"schema: {STATE_SPACE_SCHEMA}\ndefault_state: matrix-000000\n"
            "matrix: {mode: [first, first]}\n",
            "duplicate values",
        ),
        (
            f"schema: {STATE_SPACE_SCHEMA}\ndefault_state: baseline\n"
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
    "relative, rows",
    [
        ("athletes/field", 29),
        ("athletes/overview", 29),
        ("earthquakes/operations", 138),
        ("occupancy/monitor", 12),
        ("occupancy/model-review", 3),
        ("occupancy/pdf-report", 3),
    ],
)
def test_example_state_spaces_cover_their_finite_control_domains(
    relative: str,
    rows: int,
) -> None:
    source = load_state_space_source(_EXAMPLES / relative)
    assert source.state_space is not None
    assert len(source.state_space.states) == rows
