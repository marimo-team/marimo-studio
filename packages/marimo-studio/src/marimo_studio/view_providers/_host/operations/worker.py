"""Child-process entry point for one installed provider call."""

from __future__ import annotations

import inspect
import json
import sys
from importlib.metadata import EntryPoint
from pathlib import Path, PurePosixPath
from typing import cast

from marimo_studio._processes.provider_runner import create_provider_runner
from marimo_studio.view_providers import (
    BuildProfile,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderCancellation,
    ViewProvider,
)
from marimo_studio.view_providers._host.conformance import ProviderConformance

from .codec import (
    availability_payload,
    build_result_payload,
    created_files_payload,
    inspection_from_payload,
    inspection_payload,
    project_from_payload,
    provider_info_payload,
    starter_context_from_payload,
    starter_from_payload,
    starters_payload,
)


def _record(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has invalid fields")
    return cast(dict[str, object], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a string")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _load_provider(
    value: object,
) -> tuple[ViewProvider, ProviderConformance]:
    provider_data = _record(
        value,
        {"key", "registration", "distribution", "version", "entry_point"},
        "provider",
    )
    key = _text(provider_data["key"], "Provider key")
    registration = _text(provider_data["registration"], "Provider registration")
    distribution = _text(provider_data["distribution"], "Provider distribution")
    version = _text(provider_data["version"], "Provider version")
    implementation = cast(
        ViewProvider,
        EntryPoint(
            name=registration,
            value=_text(provider_data["entry_point"], "Provider entry point"),
            group="marimo_studio.view_provider",
        ).load(),
    )
    for method in ("availability", "starters", "create", "inspect", "build"):
        operation = getattr(implementation, method, None)
        if not callable(operation):
            raise ValueError(f"provider requires {method}()")
        if inspect.iscoroutinefunction(operation):
            raise ValueError(f"provider {method}() must be synchronous")
    return implementation, ProviderConformance(
        key,
        getattr(implementation, "info", None),
        distribution=distribution,
        version=version,
    )


def _invoke(payload: object, transfer_root: Path) -> object:
    root = _record(payload, {"schema", "operation", "provider", "request"}, "request")
    if root["schema"] != 1:
        raise ValueError("Provider operation schema is unsupported")
    implementation, conformance = _load_provider(root["provider"])
    request_data = cast(dict[str, object], root["request"])
    operation = root["operation"]
    if operation == "describe":
        _record(request_data, set(), "provider description")
        return provider_info_payload(conformance.info)
    if operation == "availability":
        data = _record(request_data, {"project"}, "provider availability")
        project = (
            None
            if data["project"] is None
            else conformance.validate_project(project_from_payload(data["project"]))
        )
        return availability_payload(
            conformance.validate_availability(implementation.availability(project))
        )
    if operation == "starters":
        _record(request_data, set(), "provider starters")
        return starters_payload(
            conformance.validate_starters(implementation.starters())
        )
    if operation == "create":
        data = _record(
            request_data,
            {"starter", "context"},
            "provider starter creation",
        )
        starter = conformance.validate_starters(
            (starter_from_payload(data["starter"]),)
        )[0]
        files = conformance.validate_created_files(
            starter,
            implementation.create(
                starter,
                starter_context_from_payload(data["context"]),
            ),
        )
        return created_files_payload(files, transfer_root)
    if operation == "inspect":
        return inspection_payload(_inspect(implementation, conformance, request_data))
    if operation == "build":
        return build_result_payload(_build(implementation, conformance, request_data))
    raise ValueError("Provider operation is unsupported")


def _inspect(
    provider: ViewProvider,
    conformance: ProviderConformance,
    value: object,
) -> ProjectInspection:
    data = _record(value, {"project", "cache_root", "command_timeout"}, "inspection")
    project = project_from_payload(data["project"])
    timeout = _number(data["command_timeout"], "Inspection command timeout")
    cancellation = ProviderCancellation()
    request = conformance.validate_inspection_request(
        InspectionRequest(
            project,
            create_provider_runner(
                project,
                cancellation,
                timeout,
                owns_process_tree=False,
            ),
            cancellation,
            Path(_text(data["cache_root"], "Inspection cache root")),
            timeout,
        )
    )
    return conformance.validate_inspection(project, provider.inspect(request))


def _build(
    provider: ViewProvider,
    conformance: ProviderConformance,
    value: object,
) -> BuildResult:
    data = _record(
        value,
        {
            "project",
            "inspection",
            "inputs",
            "project_revision",
            "profile",
            "staging_root",
            "cache_root",
            "command_timeout",
        },
        "build",
    )
    project = project_from_payload(data["project"])
    timeout = _number(data["command_timeout"], "Build command timeout")
    inputs = data["inputs"]
    if not isinstance(inputs, list):
        raise ValueError("Build inputs must be an array")
    cancellation = ProviderCancellation()
    request = conformance.validate_build_request(
        BuildRequest(
            project,
            inspection_from_payload(data["inspection"]),
            tuple(PurePosixPath(_text(item, "Build input")) for item in inputs),
            _text(data["project_revision"], "Project revision"),
            cast(BuildProfile, data["profile"]),
            Path(_text(data["staging_root"], "Build staging root")),
            Path(_text(data["cache_root"], "Build cache root")),
            cancellation,
            create_provider_runner(
                project,
                cancellation,
                timeout,
                owns_process_tree=False,
            ),
            timeout,
        )
    )
    return conformance.validate_build_result(request, provider.build(request))


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    request_path = Path(sys.argv[1])
    response_path = Path(sys.argv[2])
    try:
        value = _invoke(
            json.loads(request_path.read_text(encoding="utf-8")),
            response_path.parent / "transfer",
        )
        response: dict[str, object] = {"schema": 1, "ok": True, "value": value}
    except BaseException as error:
        response = {
            "schema": 1,
            "ok": False,
            "value": f"{type(error).__name__}: {error}",
        }
    response_path.write_text(
        json.dumps(response, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
