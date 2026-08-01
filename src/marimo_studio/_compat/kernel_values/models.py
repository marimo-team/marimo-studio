"""Messages shared by the Studio kernel value bridge."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio.errors import ProtocolError

NAMESPACE = "_marimo_studio"
FUNCTION_NAME = "read_values"
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


@dataclass(frozen=True)
class ValueReadError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ValueReadResult:
    values: dict[str, object]
    errors: dict[str, ValueReadError]

    def to_dict(self) -> dict[str, object]:
        return {
            "values": self.values,
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
        }
