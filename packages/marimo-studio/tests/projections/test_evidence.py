from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ProjectionResolutionError,
    resolve_projection,
)
from marimo_studio._server.presentation import evidence_policy
from marimo_studio._server.presentation.evidence import validate_projection_evidence
from marimo_studio._server.presentation.service import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._server.runtime.catalog import RuntimeProjection
from marimo_studio._validation.evidence import (
    BrowserObservation,
    ObservedProjectionInstance,
)
from marimo_studio.errors import ProtocolError

from ..app_helpers import configured


def _runtime(snapshot: PresentationSnapshot) -> RuntimeProjection:
    cell_refs = snapshot.resolved.runtime_cell_refs(None)
    return RuntimeProjection(
        "runtime-instance",
        {},
        cell_refs,
        {runtime_id: ref for ref, runtime_id in cell_refs.items()},
        {
            cell_refs[str(producer)]: tuple(
                cell_refs[str(reference)]
                for reference in snapshot.symbols.dependency_closure(producer)
            )
            for producer in snapshot.symbols.cells
        },
    )


def _ready_observation(
    snapshot: PresentationSnapshot,
    runtime: RuntimeProjection,
) -> BrowserObservation:
    instances: list[ObservedProjectionInstance] = []
    for index, mount in enumerate(snapshot.mounts):
        targets = mount.allowed_targets
        if targets is None:
            continue
        target = targets[0]
        projection = resolve_projection(
            snapshot.symbols,
            snapshot.mounts,
            ProjectionRequest(
                site_id=mount.id,
                instance_id=f"projection-{index}",
                target=target,
            ),
        )
        instances.append(
            ObservedProjectionInstance(
                mount_id=mount.id,
                instance_id=f"projection-{index}",
                target=target,
                runtime_cell_id=runtime.cell_refs[str(projection.producer)],
                phase="ready",
            )
        )
    return BrowserObservation(
        view=snapshot.view_name,
        runtime="server",
        revision=snapshot.revision,
        state="ready",
        runtime_instance=runtime.instance,
        projection_instances=tuple(instances),
    )


def _snapshot(notebook_path: Path) -> PresentationSnapshot:
    studio = configured(notebook_path)
    return NotebookPresentation(studio.notebook).snapshot("dashboard")


def test_server_derives_mount_authorization_and_runtime_identity(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    runtime = _runtime(snapshot)
    observation = _ready_observation(snapshot, runtime)

    validate_projection_evidence(observation, snapshot, runtime)

    forged = replace(
        observation.projection_instances[0],
        runtime_cell_id="forged-cell",
    )
    with pytest.raises(ProtocolError, match="runtime cell"):
        validate_projection_evidence(
            replace(observation, projection_instances=(forged,)),
            snapshot,
            runtime,
        )


def test_resolution_failure_requires_the_server_derived_error_code(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    runtime = _runtime(snapshot)
    mount = snapshot.mounts[0]
    target = "missing-target"
    with pytest.raises(ProjectionResolutionError) as captured:
        resolve_projection(
            snapshot.symbols,
            snapshot.mounts,
            ProjectionRequest(
                site_id=mount.id,
                instance_id="projection-missing",
                target=target,
            ),
        )
    failed = ObservedProjectionInstance(
        mount_id=mount.id,
        instance_id="projection-missing",
        target=target,
        runtime_cell_id=None,
        phase="error",
        error={"code": captured.value.code, "message": str(captured.value)},
    )
    observation = BrowserObservation(
        view=snapshot.view_name,
        runtime="server",
        revision=snapshot.revision,
        state="error",
        runtime_instance=runtime.instance,
        projection_instances=(failed,),
    )

    validate_projection_evidence(observation, snapshot, runtime)

    with pytest.raises(ProtocolError, match="failure"):
        validate_projection_evidence(
            replace(
                observation,
                projection_instances=(
                    replace(failed, error={"code": "forged", "message": "forged"}),
                ),
            ),
            snapshot,
            runtime,
        )


def test_unresolved_mounts_do_not_consume_the_server_target_quota(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(notebook_path)
    runtime = _runtime(snapshot)
    mount = next(item for item in snapshot.mounts if item.kind == "value")
    assert mount.allowed_targets is not None
    target = mount.allowed_targets[0]
    projection = resolve_projection(
        snapshot.symbols,
        snapshot.mounts,
        ProjectionRequest(
            site_id=mount.id,
            instance_id="projection-ready",
            target=target,
        ),
    )
    missing = ObservedProjectionInstance(
        mount_id=mount.id,
        instance_id="projection-missing",
        target="missing",
        runtime_cell_id=None,
        phase="error",
        error={
            "code": "projection-target-not-allowed",
            "message": "The target is unavailable.",
        },
    )
    ready = ObservedProjectionInstance(
        mount_id=mount.id,
        instance_id="projection-ready",
        target=target,
        runtime_cell_id=runtime.cell_refs[str(projection.producer)],
        phase="ready",
    )
    observation = BrowserObservation(
        view=snapshot.view_name,
        runtime="server",
        revision=snapshot.revision,
        state="error",
        runtime_instance=runtime.instance,
        projection_instances=(missing, ready),
    )
    monkeypatch.setattr(evidence_policy, "MAX_UNIQUE_VALUE_TARGETS", 1)

    validate_projection_evidence(observation, snapshot, runtime)


def test_stale_runtime_binding_cannot_be_reported_ready(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    runtime = _runtime(snapshot)
    observation = _ready_observation(snapshot, runtime)
    stale = replace(runtime, current_cell_refs={})

    with pytest.raises(ProtocolError, match="failure"):
        validate_projection_evidence(observation, snapshot, stale)


def test_observation_identity_must_match_the_requested_revision(
    notebook_path: Path,
) -> None:
    snapshot = _snapshot(notebook_path)
    runtime = _runtime(snapshot)
    observation = _ready_observation(snapshot, runtime)

    with pytest.raises(ProtocolError, match="presentation revision"):
        validate_projection_evidence(
            replace(observation, revision="other-revision"),
            snapshot,
            runtime,
        )
