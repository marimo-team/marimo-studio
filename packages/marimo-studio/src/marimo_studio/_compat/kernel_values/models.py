"""Messages shared by Studio's kernel functions."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio.errors import ProtocolError

NAMESPACE = "_marimo_studio"
FUNCTION_NAME = "read_values"
QUERY_FUNCTION_NAME = "sync_query"
DEFAULT_MAX_VALUE_BYTES = 1_000_000


class ValueReadUnavailable(ProtocolError):
    """A transient or terminal failure at the kernel RPC boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        transient: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.status_code = status_code or (503 if transient else 500)


@dataclass
class ReadValuesArgs:
    selectors: list[str]
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES


@dataclass
class SyncQueryArgs:
    query: dict[str, str | list[str]]
