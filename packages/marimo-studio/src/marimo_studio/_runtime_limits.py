"""Shared runtime-analysis deadlines."""

DEFAULT_RUNTIME_TIMEOUT = 60.0
MAX_RUNTIME_TIMEOUT = 300.0
RUNTIME_SHUTDOWN_GRACE = 10.0


def runtime_process_timeout(runtime_timeout: float) -> float:
    """Include kernel shutdown in the isolated worker deadline."""
    return runtime_timeout + RUNTIME_SHUTDOWN_GRACE


__all__ = [
    "DEFAULT_RUNTIME_TIMEOUT",
    "MAX_RUNTIME_TIMEOUT",
    "runtime_process_timeout",
]
