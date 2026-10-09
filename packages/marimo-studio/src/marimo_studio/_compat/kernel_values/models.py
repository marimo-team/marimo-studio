"""Messages shared by Studio's kernel functions."""

from __future__ import annotations

from dataclasses import dataclass

from marimo_studio._projections.runtime_records import MAX_OUTPUT_BYTES

NAMESPACE = "_marimo_studio"
FUNCTION_NAME = "read_values"
OUTPUT_FUNCTION_NAME = "render_values"
QUERY_FUNCTION_NAME = "sync_query"
BARRIER_FUNCTION_NAME = "execution_barrier"
OUTPUT_OWNER_PREFIX = "__marimo_studio_output_"


@dataclass
class ReadValuesArgs:
    revision: str
    projections: list[object]
    active_projections: list[object]
    consumer_id: str
    authorization: str
    max_json_bytes: int | None = None


@dataclass
class ExecutionBarrierArgs:
    """Arguments for the queue barrier used by live runtime snapshots."""

    pass


@dataclass
class RenderValuesArgs:
    revision: str
    projections: list[object]
    active_projections: list[object]
    consumer_id: str
    authorization: str
    max_output_bytes: int = MAX_OUTPUT_BYTES


@dataclass
class SyncQueryArgs:
    query: dict[str, str | list[str]]
    operation_id: str
    fingerprint: str
    binding_generation: int
    query_generation: int
    deadline: float
    session_id: str
    authorization: str
