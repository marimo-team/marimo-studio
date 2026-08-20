"""Preserve primary failures while attempting owned resource cleanup."""

from __future__ import annotations

from collections.abc import Callable


def attempt_cleanup(primary: BaseException, action: Callable[[], None]) -> None:
    """Run cleanup and append any failure to the primary exception chain."""

    try:
        action()
    except BaseException as cleanup:
        current = primary
        seen = {id(primary)}
        while current.__cause__ is not None and id(current.__cause__) not in seen:
            current = current.__cause__
            seen.add(id(current))
        if id(cleanup) not in seen:
            current.__cause__ = cleanup


__all__ = ["attempt_cleanup"]
