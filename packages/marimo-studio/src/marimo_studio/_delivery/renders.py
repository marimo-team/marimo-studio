"""Render each of a view's renders once for every state in a static export.

A static bundle has no server to render against. The Prepared runtime knows
which exported state a reader is viewing, so the export renders every declared
render with each state's values, outputs, and cells, and stores each distinct
bundle once beneath the view's support directory, where a live view serves
them too. ``renders/index.json`` lists each bundle's files and regions once,
under its ID, and maps each state fingerprint to the bundle ID, warnings, and
absent reads of each render, so the page resolves a state's files without
guessing names. A view whose renders read no notebook results has no prepared
states, so its index holds one state, keyed by the artifact revision, rendered
once.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import cast

from marimo_export.reader import ExportState

from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._delivery.urls import SUPPORT_PATH
from marimo_studio._filesystem.files import FileTree
from marimo_studio._prepared.compiler import TargetBindings
from marimo_studio._prepared.static import StaticPublication
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._projections.runtime_records import output_representation
from marimo_studio._views.records import DiagnosticsError
from marimo_studio._views.renders import (
    RenderBundle,
    absent_reads,
    canonical_values,
    read_accept,
    render_key,
    run_render,
    value_not_json,
)
from marimo_studio._workspace.tools import notebook_tools
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers import (
    JsonValue,
    ProjectDiagnostic,
    ProviderCancellation,
    Representation,
)
from marimo_studio.view_providers._artifact_sites import read_sites
from marimo_studio.view_providers._host import provider_registry

RENDERS_ROOT = PurePosixPath("renders")
MAX_STATIC_RENDERS = 256


def _publication_error(
    source: PurePosixPath, diagnostic: ProjectDiagnostic
) -> PublicationError:
    return PublicationError(
        f"{source} could not render an exported state: {diagnostic.message}",
        code=diagnostic.code,
        hint=diagnostic.hint or "Fix the render's source, then export it again.",
    )


def _state_values(
    source: PurePosixPath,
    state: ExportState,
    bindings: Mapping[str, str],
) -> tuple[dict[str, JsonValue], bytes]:
    values: dict[str, object] = {}
    for target, name in bindings.items():
        output = state.output(name)
        if output.codec != "marimo.json.v1":
            raise _publication_error(
                source, value_not_json(target, "it exported as a table")
            )
        values[target] = output.json()
    try:
        return canonical_values(values)
    except DiagnosticsError as error:
        raise _publication_error(source, error.diagnostics[0]) from error


def _state_outputs(
    state: ExportState,
    bindings: Mapping[str, str],
) -> dict[str, Representation]:
    outputs: dict[str, Representation] = {}
    for target, name in bindings.items():
        asset = state.output(name).blob_asset()
        if asset.media_type is not None and asset.data:
            size = asset.metadata
            # Representation validates the size the media exporter recorded.
            outputs[target] = Representation(
                asset.media_type,
                asset.data,
                cast("int | None", size.get("width")),
                cast("int | None", size.get("height")),
            )
    return outputs


def _state_cells(
    state: ExportState,
    bindings: Mapping[str, str],
    accept: Mapping[str, tuple[str, ...]],
) -> dict[str, Representation]:
    cells: dict[str, Representation] = {}
    for target, name in bindings.items():
        output = json.loads(state.output(name).asset_bytes())["output"]
        if output is None:
            continue
        media = output_representation(
            output["mimetype"], output["data"], accept.get(target, ())
        )
        if media is not None:
            cells[target] = media
    return cells


def write_static_renders(
    lease: ArtifactLease,
    publication: StaticPublication | None,
    bundle: FileTree,
    view_name: str,
) -> int:
    """Render every declared render for every prepared state into the bundle.

    Returns the number of files written.
    """
    artifact = lease.artifact
    template = artifact.template
    if template is None:
        return 0
    states: Sequence[ExportState | None] = (
        publication.prepared.open().states() if publication is not None else (None,)
    )
    if len(states) * len(template.renders) > MAX_STATIC_RENDERS:
        raise PublicationError(
            f"The view renders {len(template.renders)} files for each of its "
            f"{len(states)} prepared states. Static exports run at most "
            f"{MAX_STATIC_RENDERS} renders.",
            code="render-states-exceeded",
            hint="Narrow the view's state space, then export it again.",
        )
    renders_bindings = publication.bindings.renders if publication is not None else {}
    provider = provider_registry().get(artifact.provider.key)
    cancellation = current_provider_cancellation() or ProviderCancellation()
    root = bundle.root.joinpath(
        *PurePosixPath(SUPPORT_PATH.removeprefix("/")).parts,
        "views",
        view_name,
        *RENDERS_ROOT.parts,
    )

    def fingerprint(state: ExportState | None) -> str:
        return (
            state.fingerprint
            if state is not None
            else artifact.artifact_revision.removeprefix("sha256:")
        )

    index: dict[str, dict[str, object]] = {fingerprint(state): {} for state in states}
    stored: dict[str, RenderBundle] = {}
    written = 0
    with (
        notebook_tools(lease.project.locations.notebook),
        tempfile.TemporaryDirectory(prefix="marimo-studio-export-renders-") as scratch,
    ):
        # Every render of the export copies one template verified once.
        verified = Path(scratch, "template")
        lease.copy_template(verified)

        def copy_template(destination: Path) -> None:
            shutil.copytree(verified, destination, copy_function=shutil.copyfile)

        for source in template.renders:
            bindings = renders_bindings.get(
                source.as_posix(), TargetBindings({}, {}, {})
            )
            sites = read_sites(artifact.sites, source)
            accept = read_accept(sites, "cell")
            by_key: dict[bytes, tuple[RenderBundle, list[str]]] = {}
            for state in states:
                if state is None:
                    values, encoded = canonical_values({})
                    outputs: dict[str, Representation] = {}
                    cells: dict[str, Representation] = {}
                else:
                    values, encoded = _state_values(source, state, bindings.values)
                    outputs = _state_outputs(state, bindings.outputs)
                    cells = _state_cells(state, bindings.cells, accept)
                key = render_key(source, encoded, outputs, cells)
                if key not in by_key:
                    try:
                        rendered = run_render(
                            provider,
                            copy_template,
                            source,
                            sites,
                            values,
                            outputs,
                            cells,
                            cancellation,
                            Path(tempfile.mkdtemp(dir=scratch), "bundle"),
                        )
                    except DiagnosticsError as error:
                        raise _publication_error(
                            source, error.diagnostics[0]
                        ) from error
                    # Identical files share one bundle, and each input set
                    # keeps its own warnings.
                    shared = stored.setdefault(rendered.id, rendered)
                    by_key[key] = (
                        replace(shared, warnings=rendered.warnings),
                        absent_reads(sites, values, outputs, cells),
                    )
                result, absent = by_key[key]
                index[fingerprint(state)][source.as_posix()] = {
                    "bundle": result.id,
                    "warnings": [item.to_dict() for item in result.warnings],
                    "absent": absent,
                }
        for result in stored.values():
            destination = root / result.id
            for item in result.files:
                target = destination.joinpath(*item.path.parts)
                bundle.ensure_directory(target.parent)
                shutil.copyfile(result.root.joinpath(*item.path.parts), target)
                target.chmod(0o644)
                written += 1
    bundles = {
        result.id: {
            key: value
            for key, value in result.to_dict().items()
            if key in ("files", "main", "preview", "regions")
        }
        for result in stored.values()
    }
    bundle.ensure_directory(root)
    bundle.write(
        root / "index.json",
        json.dumps(
            {"schema": 2, "bundles": bundles, "states": index}, sort_keys=True
        ).encode(),
        mode=0o644,
    )
    return written + 1
