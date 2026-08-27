"""Static and runtime validation result records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, TypeAlias

CheckStatus: TypeAlias = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    code: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.code is None:
            value.pop("code")
        if self.details is None:
            value.pop("details")
        return value
