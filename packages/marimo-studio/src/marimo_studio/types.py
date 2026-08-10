"""Studio-owned records shared across inspection and runtime boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeAlias

Scope: TypeAlias = MutableMapping[str, Any]
Message: TypeAlias = MutableMapping[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[Message]]
Send: TypeAlias = Callable[[Message], Awaitable[None]]


class ASGIApp(Protocol):
    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None: ...


@dataclass(frozen=True, order=True)
class CellRef:
    fingerprint: str
    layout_fingerprint: str
    occurrence: int = 0

    PREFIX = "cell:v1:"

    def __post_init__(self) -> None:
        fingerprint = self._digest(self.fingerprint)
        layout_fingerprint = self._digest(self.layout_fingerprint)
        if self.occurrence < 0:
            raise ValueError("Cell reference occurrence must be non-negative")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "layout_fingerprint", layout_fingerprint)

    @staticmethod
    def _digest(value: str) -> str:
        digest = value.lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Cell references require full SHA-256 digests")
        return digest

    @classmethod
    def parse(cls, value: CellRef | str) -> CellRef:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("Cell reference must be a string or CellRef")
        if not value.startswith(cls.PREFIX):
            raise ValueError(f"Invalid cell reference: {value}")
        payload, separator, occurrence = value.removeprefix(cls.PREFIX).rpartition(":")
        fingerprint, digest_separator, layout_fingerprint = payload.partition(":")
        if not separator or not digest_separator:
            raise ValueError(f"Invalid cell reference: {value}")
        try:
            occurrence_index = int(occurrence)
        except ValueError as error:
            raise ValueError(f"Invalid cell reference occurrence: {value}") from error
        return cls(fingerprint, layout_fingerprint, occurrence_index)

    def __str__(self) -> str:
        return (
            f"{self.PREFIX}{self.fingerprint}:{self.layout_fingerprint}:"
            f"{self.occurrence}"
        )


@dataclass(frozen=True)
class LiveCellIdentity:
    """One cell identity currently present in a Marimo session."""

    ref: CellRef
    runtime_id: str


@dataclass(frozen=True)
class LiveCellSnapshot:
    """Cell identities currently present in one Marimo session."""

    ids: Mapping[CellRef, str]
    names: Mapping[str, tuple[LiveCellIdentity, ...]]


@dataclass(frozen=True)
class SourceSpan:
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0


@dataclass(frozen=True)
class CellConfigSpec:
    column: int | None
    disabled: bool
    hide_code: bool


@dataclass(frozen=True)
class CellSpec:
    ref: CellRef
    runtime_id: str
    index: int
    name: str | None
    source: SourceSpan
    code_sha256: str
    preview: str
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    upstream: tuple[CellRef, ...]
    downstream: tuple[CellRef, ...]
    config: CellConfigSpec
    has_output_expression: bool
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["ref"] = str(self.ref)
        value["upstream"] = [str(ref) for ref in self.upstream]
        value["downstream"] = [str(ref) for ref in self.downstream]
        if self.code is None:
            value.pop("code")
        return value


ValuePathKind: TypeAlias = Literal["attribute", "item"]


@dataclass(frozen=True)
class ValuePathStep:
    kind: ValuePathKind
    value: str | int


@dataclass(frozen=True)
class ValueReference:
    source: str
    variable: str
    path: tuple[ValuePathStep, ...]


@dataclass(frozen=True)
class ValueBinding:
    reference: ValueReference
    cell: CellSpec
    source: Path
    line: int
    column: int


@dataclass(frozen=True)
class NotebookSpec:
    path: Path
    cells: tuple[CellSpec, ...]
    app_config: dict[str, Any]

    def by_ref(self) -> dict[CellRef, CellSpec]:
        return {cell.ref: cell for cell in self.cells}

    def named_cells(self) -> dict[str, CellSpec]:
        return {cell.name: cell for cell in self.cells if cell.name is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "notebook": str(self.path),
            "app_config": self.app_config,
            "cells": [cell.to_dict() for cell in self.cells],
        }


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


@dataclass(frozen=True)
class RenderedOutput:
    owner_cell_id: str
    mimetype: str
    data: str
    timestamp: float
    reset_ui_object_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "ownerCellId": self.owner_cell_id,
            "mimetype": self.mimetype,
            "data": self.data,
            "timestamp": self.timestamp,
            "resetUiObjectIds": list(self.reset_ui_object_ids),
        }


@dataclass(frozen=True)
class OutputRenderResult:
    outputs: dict[str, RenderedOutput]
    errors: dict[str, ValueReadError]

    def to_dict(self) -> dict[str, object]:
        return {
            "outputs": {
                selector: output.to_dict() for selector, output in self.outputs.items()
            },
            "errors": {
                selector: error.to_dict() for selector, error in self.errors.items()
            },
        }


@dataclass(frozen=True)
class RuntimeOutput:
    channel: str
    mimetype: str
    empty: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "mimetype": self.mimetype,
            "empty": self.empty,
        }


@dataclass(frozen=True)
class RuntimeCell:
    status: str | None
    outputs: tuple[RuntimeOutput, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "outputs": [output.to_dict() for output in self.outputs],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class RuntimeProbe:
    cells: dict[str, RuntimeCell]
    values: ValueReadResult
    outputs: OutputRenderResult
