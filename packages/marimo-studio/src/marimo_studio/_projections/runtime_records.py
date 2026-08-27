"""Runtime value, output, and cell probe records."""

from __future__ import annotations

from dataclasses import dataclass


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
