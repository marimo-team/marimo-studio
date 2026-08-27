"""Run installed provider calls in owned processes."""

from __future__ import annotations

import json
import math
import os
import stat
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TypeVar, cast

from marimo_studio._processes.supervisor import ProcessCleanupError, ProcessSupervisor
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderInfo,
    ProviderStarter,
    StarterContext,
    ViewProject,
)

from .codec import (
    availability_from_payload,
    build_result_from_payload,
    created_files_from_payload,
    inspection_from_payload,
    inspection_payload,
    project_payload,
    provider_info_from_payload,
    starter_context_payload,
    starter_payload,
    starters_from_payload,
)

_RESULT_LIMIT = 16 * 1024 * 1024
_PROVIDER_OPERATION_OVERHEAD = 10.0
DEFAULT_PROVIDER_EXTENSION_TIMEOUT = 10.0
_Decoded = TypeVar("_Decoded")


class ProviderOperationError(RuntimeError):
    """An isolated provider operation did not reach a valid terminal result."""


class ProviderOperationCancelled(ProviderOperationError):
    """The owner cancelled an isolated provider operation."""


@dataclass(frozen=True)
class ProviderProcessSpec:
    key: str
    registration: str
    distribution: str
    version: str
    entry_point: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "registration": self.registration,
            "distribution": self.distribution,
            "version": self.version,
            "entry_point": self.entry_point,
        }


def inspect_in_provider_process(
    spec: ProviderProcessSpec,
    request: InspectionRequest,
) -> ProjectInspection:
    payload: dict[str, object] = {
        "schema": 1,
        "operation": "inspect",
        "provider": spec.to_dict(),
        "request": {
            "project": project_payload(request.project),
            "cache_root": str(request.cache_root),
            "command_timeout": request.command_timeout,
        },
    }
    return inspection_from_payload(
        _run_provider_process(
            payload,
            request.cancellation,
            _operation_timeout(request.command_timeout),
        )
    )


def build_in_provider_process(
    spec: ProviderProcessSpec,
    request: BuildRequest,
) -> BuildResult:
    payload: dict[str, object] = {
        "schema": 1,
        "operation": "build",
        "provider": spec.to_dict(),
        "request": {
            "project": project_payload(request.project),
            "inspection": inspection_payload(request.inspection),
            "inputs": [item.as_posix() for item in request.inputs],
            "project_revision": request.project_revision,
            "profile": request.profile,
            "staging_root": str(request.staging_root),
            "cache_root": str(request.cache_root),
            "command_timeout": request.command_timeout,
        },
    }
    return build_result_from_payload(
        _run_provider_process(
            payload,
            request.cancellation,
            _operation_timeout(request.command_timeout),
        )
    )


def describe_in_provider_process(
    spec: ProviderProcessSpec,
    cancellation: ProviderCancellation,
    timeout: float = DEFAULT_PROVIDER_EXTENSION_TIMEOUT,
) -> ProviderInfo:
    return provider_info_from_payload(
        _run_provider_process(
            {
                "schema": 1,
                "operation": "describe",
                "provider": spec.to_dict(),
                "request": {},
            },
            cancellation,
            timeout,
        )
    )


def availability_in_provider_process(
    spec: ProviderProcessSpec,
    project: ViewProject | None,
    cancellation: ProviderCancellation,
    timeout: float = DEFAULT_PROVIDER_EXTENSION_TIMEOUT,
) -> ProviderAvailability:
    return availability_from_payload(
        _run_provider_process(
            {
                "schema": 1,
                "operation": "availability",
                "provider": spec.to_dict(),
                "request": {
                    "project": None if project is None else project_payload(project),
                },
            },
            cancellation,
            timeout,
        )
    )


def starters_in_provider_process(
    spec: ProviderProcessSpec,
    cancellation: ProviderCancellation,
    timeout: float = DEFAULT_PROVIDER_EXTENSION_TIMEOUT,
) -> tuple[ProviderStarter, ...]:
    return starters_from_payload(
        _run_provider_process(
            {
                "schema": 1,
                "operation": "starters",
                "provider": spec.to_dict(),
                "request": {},
            },
            cancellation,
            timeout,
        )
    )


def create_in_provider_process(
    spec: ProviderProcessSpec,
    starter: ProviderStarter,
    context: StarterContext,
    cancellation: ProviderCancellation,
    timeout: float = DEFAULT_PROVIDER_EXTENSION_TIMEOUT,
) -> Mapping[PurePosixPath, bytes]:
    value = _run_provider_process(
        {
            "schema": 1,
            "operation": "create",
            "provider": spec.to_dict(),
            "request": {
                "starter": starter_payload(starter),
                "context": starter_context_payload(context),
            },
        },
        cancellation,
        timeout,
        decoder=created_files_from_payload,
    )
    return cast(Mapping[PurePosixPath, bytes], value)


def _operation_timeout(command_timeout: float) -> float:
    timeout = command_timeout + _PROVIDER_OPERATION_OVERHEAD
    if not math.isfinite(timeout):
        raise ProviderOperationError(
            "Provider command timeout leaves no room for operation cleanup"
        )
    return timeout


def _run_provider_process(
    payload: dict[str, object],
    cancellation: ProviderCancellation,
    timeout: float,
    *,
    decoder: Callable[[object, Path], _Decoded] | None = None,
) -> object | _Decoded:
    if cancellation.cancelled:
        raise ProviderOperationCancelled("Provider operation was cancelled")
    supervisor = ProcessSupervisor()
    unregister = cancellation.register(supervisor.cancel)
    try:
        with TemporaryDirectory(prefix="marimo-studio-provider-") as directory:
            root = Path(directory)
            request_path = root / "request.json"
            response_path = root / "response.json"
            request_path.write_text(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                completed = supervisor.run(
                    [
                        sys.executable,
                        "-m",
                        "marimo_studio.view_providers._host.operations.worker",
                        str(request_path),
                        str(response_path),
                    ],
                    timeout,
                    env=os.environ.copy(),
                )
            except (OSError, ProcessCleanupError) as error:
                if cancellation.cancelled:
                    raise ProviderOperationCancelled(
                        "Provider operation was cancelled"
                    ) from error
                raise ProviderOperationError(str(error)) from error
            if cancellation.cancelled:
                raise ProviderOperationCancelled("Provider operation was cancelled")
            if completed.timed_out:
                raise ProviderOperationError(
                    f"Provider operation exceeded its {timeout:g} second limit"
                )
            if completed.output_too_large:
                raise ProviderOperationError(
                    "Provider operation produced too much output"
                )
            if completed.returncode != 0 and not response_path.exists():
                detail = completed.stderr.decode(errors="replace").strip()
                raise ProviderOperationError(
                    detail
                    or f"Provider process exited with status {completed.returncode}"
                )
            response = json.loads(_read_response(response_path))
            if not isinstance(response, dict) or set(response) != {
                "schema",
                "ok",
                "value",
            }:
                raise ProviderOperationError(
                    "Provider operation returned an invalid response"
                )
            if response["schema"] != 1 or type(response["ok"]) is not bool:
                raise ProviderOperationError(
                    "Provider operation returned an invalid response"
                )
            if not response["ok"]:
                error = response["value"]
                raise ProviderOperationError(
                    error
                    if isinstance(error, str) and error
                    else "Provider operation failed"
                )
            value = response["value"]
            decoded = value if decoder is None else decoder(value, root / "transfer")
            if cancellation.cancelled:
                raise ProviderOperationCancelled("Provider operation was cancelled")
            return decoded
    finally:
        unregister()


def _read_response(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode) or state.st_size > _RESULT_LIMIT:
            raise ProviderOperationError("Provider operation response is invalid")
        payload = os.read(descriptor, state.st_size + 1)
        if len(payload) != state.st_size:
            raise ProviderOperationError(
                "Provider operation response changed while read"
            )
        return payload
    finally:
        os.close(descriptor)
