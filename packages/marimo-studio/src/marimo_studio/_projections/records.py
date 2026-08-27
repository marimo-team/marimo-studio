"""Restricted value selector records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

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
