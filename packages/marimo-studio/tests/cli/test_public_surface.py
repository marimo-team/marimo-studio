from __future__ import annotations

from typing import get_args, get_type_hints

import click

import marimo_studio.agent as studio_agent
import marimo_studio.authoring as studio_authoring
import marimo_studio.errors as studio_errors
from marimo_studio._cli import cli

PARITY = (
    (studio_authoring, "doctor", ("doctor",)),
    (studio_authoring.Workspace, "status", ("status",)),
    (studio_authoring.Workspace, "inspect_notebook", ("notebook", "inspect")),
    (studio_authoring.Workspace, "bind", ("notebook", "bind")),
    (studio_authoring.Workspace, "starters", ("starters",)),
    (studio_authoring.Workspace, "create_view", ("view", "create")),
    (studio_authoring.Workspace, "validate", ("validate",)),
    (studio_authoring.View, "inspect", ("view", "inspect")),
    (studio_authoring.View, "read", ("view", "read")),
    (studio_authoring.View, "write", ("view", "write")),
    (studio_authoring.View, "hold_publication", ("view", "hold")),
    (studio_authoring.View, "release_publication", ("view", "release")),
    (studio_authoring.View, "build", ("view", "build")),
    (studio_authoring.View, "preview_url", ("view", "preview")),
    (studio_agent.View, "show", ("view", "show")),
    (studio_authoring.View, "validate", ("validate",)),
    (studio_authoring.View, "export", ("view", "export")),
    (studio_authoring.View, "preflight", ("view", "preflight")),
    (studio_authoring.View, "remove", ("view", "remove")),
)


def _leaf_paths(
    group: click.Group, prefix: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for name, command in group.commands.items():
        path = (*prefix, name)
        if isinstance(command, click.Group):
            paths.update(_leaf_paths(command, path))
        else:
            paths.add(path)
    return paths


def test_python_and_cli_authoring_operations_stay_in_parity() -> None:
    for owner, member, _path in PARITY:
        assert callable(getattr(owner, member))
    assert _leaf_paths(cli) == {path for _owner, _member, path in PARITY}


def test_authoring_exports_public_records_with_resolvable_annotations() -> None:
    records = {
        "BindingResult",
        "InspectionResult",
        "OutputRenderResult",
        "ProjectionPortability",
        "PublicationHold",
        "ProviderDiagnostic",
        "ProviderReport",
        "RenderedOutput",
        "RuntimeCell",
        "RuntimeOutput",
        "RuntimeProbe",
        "Starter",
        "StaticExportEvent",
        "StaticExportProgress",
        "StaticExportResult",
        "StaticExportStep",
        "StaticPreflightIssue",
        "StaticPreflightReport",
        "StaticRuntime",
        "StudioDiagnostic",
        "StudioOverview",
        "ValidationIssue",
        "ValidationReport",
        "ValueReadError",
        "ValueReadResult",
        "View",
        "ViewBuild",
        "ViewDocument",
        "ViewInspection",
        "ViewOverview",
        "ViewRemovalResult",
        "ViewSourceChanges",
        "ViewSourceFile",
        "Workspace",
        "doctor",
        "open_workspace",
    }
    assert records == set(studio_authoring.__all__)
    for name in records - {"StaticExportEvent", "StaticRuntime"}:
        get_type_hints(getattr(studio_authoring, name))
    assert set(get_args(studio_authoring.StaticRuntime)) == {"zero-python", "wasm"}


def test_expected_errors_are_public() -> None:
    assert set(studio_errors.__all__) == {
        "AgentRequestError",
        "BindingError",
        "CapabilityInputError",
        "ConfigurationError",
        "DependencyError",
        "LastViewError",
        "MarimoStudioError",
        "NotebookSourceError",
        "ProtocolError",
        "ProviderNotFoundError",
        "PublicationError",
        "PublicationLimitError",
        "PublicationUnavailableError",
        "RuntimeConfigTooLargeError",
        "RuntimeSelectionError",
        "RuntimeTimeoutError",
        "SourceConflictError",
        "SourceEncodingError",
        "SourceNotFoundError",
        "SourceTooLargeError",
        "SourceValidationError",
        "StaticExportError",
        "ViewDeletionError",
        "ViewExistsError",
        "ViewGenerationConflictError",
        "ViewInUseError",
        "ViewNotFoundError",
        "ViewProjectError",
        "WorkspaceGenerationConflictError",
        "WorkspaceMutationError",
    }
    assert studio_errors.ViewDeletionError.code == "view-deletion-error"
    assert studio_errors.ViewInUseError.code == "view-in-use"
