"""Messages shared by Studio's kernel functions."""

from __future__ import annotations

from dataclasses import dataclass

NAMESPACE = "_marimo_studio"
FUNCTION_NAME = "read_values"
OUTPUT_FUNCTION_NAME = "render_values"
QUERY_FUNCTION_NAME = "sync_query"
OUTPUT_OWNER_PREFIX = "__marimo_studio_output_"
DEFAULT_MAX_VALUE_BYTES = 1_000_000


@dataclass
class ReadValuesArgs:
    selectors: list[str]
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES


@dataclass
class RenderValuesArgs:
    selectors: list[str]
    active_selectors: list[str]
    consumer_id: str
    max_output_bytes: int = DEFAULT_MAX_VALUE_BYTES


@dataclass
class SyncQueryArgs:
    query: dict[str, str | list[str]]
    operation_id: str = ""
