"""Find the values a prepared control can send that no prepared state holds.

A reader who moves a control of a static export to such a value keeps the
previous display, since the export holds no results for it. marimo-export
records the values each root control can send, and the export's states hold
the values Studio prepared.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from marimo_export import NotebookExport
from marimo_export.index import ControlOptions, ControlRange

# Examples listed per control, and the tolerance on a range's step index.
_EXAMPLES = 5
_INDEX_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class UncoveredControl:
    """A prepared input whose control can send values no state holds."""

    input: str
    missing: int
    examples: tuple[object, ...]


def uncovered_controls(export: NotebookExport) -> tuple[UncoveredControl, ...]:
    """Return each root control input whose states skip values it can send."""
    states = export.states()
    uncovered: dict[str, UncoveredControl] = {}
    for binding in export.control_bindings.values():
        domain = binding.domain
        if binding.path or domain is None or binding.input in uncovered:
            continue
        prepared = [state.inputs[binding.input] for state in states]
        if isinstance(domain, ControlRange):
            gap = _range_gap(domain, prepared)
        else:
            gap = _options_gap(domain, prepared)
        if gap is not None:
            uncovered[binding.input] = UncoveredControl(binding.input, *gap)
    return tuple(uncovered[name] for name in sorted(uncovered))


def _range_gap(
    domain: ControlRange, prepared: Sequence[object]
) -> tuple[int, tuple[object, ...]] | None:
    # Step indexes compare at a tolerance that scales with the step.
    last = math.floor((domain.stop - domain.start) / domain.step + _INDEX_TOLERANCE)
    covered: set[int] = set()
    for value in prepared:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        index = (value - domain.start) / domain.step
        if abs(index - round(index)) < _INDEX_TOLERANCE and 0 <= round(index) <= last:
            covered.add(round(index))
    missing = last + 1 - len(covered)
    if missing == 0:
        return None
    examples: list[object] = []
    index = 0
    while len(examples) < min(missing, _EXAMPLES):
        if index not in covered:
            examples.append(_number(domain.start + index * domain.step))
        index += 1
    return missing, tuple(examples)


def _options_gap(
    domain: ControlOptions, prepared: Sequence[object]
) -> tuple[int, tuple[object, ...]] | None:
    skipped = [value for value in domain.values if value not in prepared]
    if not skipped:
        return None
    return len(skipped), tuple(skipped[:_EXAMPLES])


def _number(value: float) -> object:
    """Return ``value`` as the frontend shows it, without float noise."""
    shown = float(f"{value:.15g}")
    return int(shown) if shown.is_integer() else shown


__all__ = ["UncoveredControl", "uncovered_controls"]
