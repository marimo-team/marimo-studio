"""Serializable execution capabilities for presentation runtimes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RuntimeProjections:
    cell: bool
    output: bool
    value: bool

    def to_dict(self) -> dict[str, bool]:
        return {
            "cell": self.cell,
            "output": self.output,
            "value": self.value,
        }


@dataclass(frozen=True)
class RuntimeDescriptor:
    id: str
    label: str
    description: str
    execution: Literal["kernel", "worker", "prepared"]
    projections: RuntimeProjections
    controls: Literal["peer", "state", "none"]
    query: Literal["reactive", "state", "none"]
    preparation: Literal["primary", "after-primary", "on-select"]
    session: Literal["shared", "isolated", "none"]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.id):
            raise ValueError(f"Invalid runtime ID {self.id!r}")
        if not self.label.strip() or self.label != self.label.strip():
            raise ValueError(f"Runtime {self.id!r} requires a trimmed label")
        if not self.description.strip() or self.description != self.description.strip():
            raise ValueError(f"Runtime {self.id!r} requires a trimmed description")
        if self.execution not in {"kernel", "worker", "prepared"}:
            raise ValueError(f"Runtime {self.id!r} has an invalid execution mode")
        if self.controls not in {"peer", "state", "none"}:
            raise ValueError(f"Runtime {self.id!r} has an invalid control mode")
        if self.query not in {"reactive", "state", "none"}:
            raise ValueError(f"Runtime {self.id!r} has an invalid query mode")
        if self.preparation not in {"primary", "after-primary", "on-select"}:
            raise ValueError(f"Runtime {self.id!r} has an invalid preparation mode")
        if self.session not in {"shared", "isolated", "none"}:
            raise ValueError(f"Runtime {self.id!r} has an invalid session mode")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "execution": self.execution,
            "projections": self.projections.to_dict(),
            "controls": self.controls,
            "query": self.query,
            "preparation": self.preparation,
            "session": self.session,
        }


SERVER_RUNTIME = RuntimeDescriptor(
    id="server",
    label="Server",
    description="Uses the notebook kernel",
    execution="kernel",
    projections=RuntimeProjections(cell=True, output=True, value=True),
    controls="peer",
    query="reactive",
    preparation="primary",
    session="shared",
)

WASM_RUNTIME = RuntimeDescriptor(
    id="wasm",
    label="WebAssembly",
    description="Runs locally in your browser",
    execution="worker",
    projections=RuntimeProjections(cell=True, output=True, value=True),
    controls="state",
    query="state",
    preparation="after-primary",
    session="isolated",
)

ZERO_PYTHON_RUNTIME = RuntimeDescriptor(
    id="zero-python",
    label="Zero-Python",
    description="Loads prepared notebook states",
    execution="prepared",
    projections=RuntimeProjections(cell=True, output=True, value=True),
    controls="state",
    query="state",
    preparation="on-select",
    session="none",
)


__all__ = [
    "SERVER_RUNTIME",
    "WASM_RUNTIME",
    "ZERO_PYTHON_RUNTIME",
    "RuntimeDescriptor",
    "RuntimeProjections",
]
