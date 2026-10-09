"""Render a document view once for each notebook state in a static export.

A static bundle has no server to render against. The Prepared runtime knows
which exported state a reader is viewing, so the export renders the document
template with each state's values, outputs, and cells and names the file after
the state fingerprint. States that read the same inputs share one render.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import cast

from marimo_export.reader import ExportState

from marimo_studio._artifacts.retention import ArtifactLease
from marimo_studio._filesystem.files import FileTree
from marimo_studio._prepared.static import StaticPublication
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._projections.runtime_records import output_representation
from marimo_studio._views.documents import (
    MAX_DOCUMENT_BYTES,
    canonical_values,
    render_document,
    render_key,
    value_not_json,
)
from marimo_studio._views.records import DiagnosticsError
from marimo_studio.errors import PublicationError
from marimo_studio.view_providers import (
    JsonValue,
    ProjectDiagnostic,
    ProviderCancellation,
    Representation,
)
from marimo_studio.view_providers._artifact_sites import media_accept
from marimo_studio.view_providers._host import provider_registry

RENDITION_ROOT = PurePosixPath("renditions")
MAX_STATIC_RENDITIONS = 256


def _publication_error(diagnostic: ProjectDiagnostic) -> PublicationError:
    return PublicationError(
        f"The document could not render an exported state: {diagnostic.message}",
        code=diagnostic.code,
        hint=diagnostic.hint or "Fix the document template, then export it again.",
    )


def _state_values(
    state: ExportState,
    bindings: Mapping[str, str],
) -> tuple[dict[str, JsonValue], bytes]:
    values: dict[str, object] = {}
    for target, name in bindings.items():
        output = state.output(name)
        if output.codec == "marimo.scalar.v1":
            values[target] = output.scalar()
        elif output.codec == "marimo.json.v1":
            values[target] = output.json()
        else:
            raise _publication_error(value_not_json(target))
    try:
        return canonical_values(values)
    except DiagnosticsError as error:
        raise _publication_error(error.diagnostics[0]) from error


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


def write_static_renditions(
    lease: ArtifactLease,
    publication: StaticPublication,
    bundle: FileTree,
) -> int:
    """Render the published template for every prepared state into the bundle.

    Returns the number of files written.
    """
    artifact = lease.artifact
    template = artifact.template
    if template is None:
        return 0
    # A document view publishes only its template's render sites, so its
    # prepared bindings are exactly the values and outputs the template reads.
    value_bindings = publication.projections["values"]
    output_bindings = publication.projections["outputs"]
    cell_bindings = publication.projections["cells"]
    cell_accept = media_accept(artifact.sites, "cell")
    states = publication.prepared.open().states()
    if len(states) > MAX_STATIC_RENDITIONS:
        raise PublicationError(
            f"The document view has {len(states)} prepared states. Static exports "
            f"render at most {MAX_STATIC_RENDITIONS}.",
            code="document-render-states-exceeded",
            hint="Narrow the view's state space, then export it again.",
        )
    provider = provider_registry().get(artifact.provider.key)
    cancellation = current_provider_cancellation() or ProviderCancellation()
    written: dict[bytes, PurePosixPath] = {}
    for state in states:
        values, encoded = _state_values(state, value_bindings)
        outputs = _state_outputs(state, output_bindings)
        cells = _state_cells(state, cell_bindings, cell_accept)
        key = render_key(encoded, outputs, cells)
        first = written.get(key)
        if first is None:
            try:
                rendition = render_document(
                    provider,
                    lease.copy_template,
                    template.document,
                    values,
                    outputs,
                    cells,
                    cancellation,
                )
            except DiagnosticsError as error:
                raise _publication_error(error.diagnostics[0]) from error
            content, suffix = rendition.content, rendition.suffix
        else:
            content = bundle.read(
                bundle.root.joinpath(*first.parts),
                max_bytes=MAX_DOCUMENT_BYTES,
            ).content
            suffix = first.suffix
        path = RENDITION_ROOT / f"{state.fingerprint}{suffix}"
        target = bundle.root.joinpath(*path.parts)
        bundle.ensure_directory(target.parent)
        bundle.write(target, content, mode=0o644)
        written.setdefault(key, path)
    return len(states)
