"""Shared runtime-analysis deadlines."""

import math

DEFAULT_RUNTIME_TIMEOUT = 60.0
MAX_RUNTIME_TIMEOUT = 300.0
RUNTIME_SHUTDOWN_GRACE = 10.0


def validate_runtime_timeout(value: object) -> None:
    """Reject a runtime deadline outside the supported finite range."""
    message = f"timeout must be a finite number between 0 and {MAX_RUNTIME_TIMEOUT:g}"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(message)
    try:
        finite = math.isfinite(value)
    except (OverflowError, ValueError):
        raise ValueError(message) from None
    if not finite or not 0 <= value <= MAX_RUNTIME_TIMEOUT:
        raise ValueError(message)


def runtime_process_timeout(runtime_timeout: float) -> float:
    """Include kernel shutdown in the isolated worker deadline."""
    return runtime_timeout + RUNTIME_SHUTDOWN_GRACE
