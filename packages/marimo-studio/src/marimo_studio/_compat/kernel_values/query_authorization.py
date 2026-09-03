"""Mint and verify server-owned kernel query mutations."""

from __future__ import annotations

import math
from pathlib import Path

from marimo_studio._compat.kernel_values.authorization_key import (
    sign_kernel_authorization,
    verify_kernel_authorization,
)


def _payload(
    *,
    fingerprint: str,
    operation_id: str,
    binding_generation: int,
    query_generation: int,
    deadline: float,
    session_id: str,
    notebook: str,
) -> dict[str, object]:
    return {
        "operation": "query",
        "fingerprint": fingerprint,
        "operationId": operation_id,
        "bindingGeneration": binding_generation,
        "queryGeneration": query_generation,
        "deadline": deadline,
        "sessionId": session_id,
        "notebook": notebook,
    }


def authorized_query_arguments(
    *,
    query: dict[str, str | list[str]],
    fingerprint: str,
    operation_id: str,
    binding_generation: int,
    query_generation: int,
    deadline: float,
    session_id: str,
    notebook: Path,
) -> dict[str, object]:
    payload = _payload(
        fingerprint=fingerprint,
        operation_id=operation_id,
        binding_generation=binding_generation,
        query_generation=query_generation,
        deadline=deadline,
        session_id=session_id,
        notebook=str(notebook),
    )
    return {
        "query": query,
        "operation_id": operation_id,
        "fingerprint": fingerprint,
        "binding_generation": binding_generation,
        "query_generation": query_generation,
        "deadline": deadline,
        "session_id": session_id,
        "authorization": sign_kernel_authorization(payload),
    }


def verify_query_authorization(args: object, notebook: Path) -> bool:
    fingerprint = getattr(args, "fingerprint", None)
    operation_id = getattr(args, "operation_id", None)
    binding_generation = getattr(args, "binding_generation", None)
    query_generation = getattr(args, "query_generation", None)
    deadline = getattr(args, "deadline", None)
    session_id = getattr(args, "session_id", None)
    authorization = getattr(args, "authorization", None)
    if (
        not isinstance(fingerprint, str)
        or not isinstance(operation_id, str)
        or isinstance(binding_generation, bool)
        or not isinstance(binding_generation, int)
        or isinstance(query_generation, bool)
        or not isinstance(query_generation, int)
        or isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(deadline)
        or not isinstance(session_id, str)
        or not isinstance(authorization, str)
    ):
        return False
    payload = _payload(
        fingerprint=fingerprint,
        operation_id=operation_id,
        binding_generation=binding_generation,
        query_generation=query_generation,
        deadline=deadline,
        session_id=session_id,
        notebook=str(notebook),
    )
    return verify_kernel_authorization(authorization, payload)
