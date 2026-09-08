"""Studio records that bind one prepared export to an authored view."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from marimo_export.publication import PreparedPublication

from marimo_studio._prepared.manifest import prepared_view_manifest
from marimo_studio._prepared.state_space import StateSpaceSource
from marimo_studio._server.presentation.service import PresentationSnapshot

_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class PreparedViewRequest:
    snapshot: PresentationSnapshot
    state_space_source: StateSpaceSource
    server: str
    server_token: str = field(repr=False)
    session_id: str
    binding_id: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            self.snapshot.view_name,
            self.binding_id,
            self.snapshot.revision,
        )

    @property
    def binding_key(self) -> tuple[str, str]:
        return self.snapshot.view_name, self.binding_id


class PreparedViewMetadata:
    """Studio-owned metadata paired with one prepared publication."""

    def __init__(
        self,
        *,
        request: PreparedViewRequest,
        projections: Mapping[str, Mapping[str, str]],
        selected_inputs: Mapping[str, object] | None,
        plan_digest: str,
    ) -> None:
        if _DIGEST.fullmatch(plan_digest) is None:
            raise ValueError("plan_digest must be a lowercase SHA-256 digest")
        if set(projections) != {"cells", "outputs", "values"}:
            raise ValueError("projections must contain cells, outputs, and values")
        self.request = request
        self.projections = {
            name: dict(sorted(values.items())) for name, values in projections.items()
        }
        self.selected_inputs = (
            None if selected_inputs is None else dict(selected_inputs)
        )
        self.plan_digest = plan_digest


class PreparedView:
    """Studio bindings around one controller-owned prepared publication."""

    def __init__(
        self,
        prepared: PreparedPublication[
            tuple[str, str, str],
            PreparedViewMetadata,
        ],
    ) -> None:
        self.prepared = prepared

    @property
    def request(self) -> PreparedViewRequest:
        return self.prepared.metadata.request

    @property
    def projections(self) -> Mapping[str, Mapping[str, str]]:
        return self.prepared.metadata.projections

    @property
    def selected_inputs(self) -> Mapping[str, object] | None:
        return self.prepared.metadata.selected_inputs

    @property
    def plan_digest(self) -> str:
        return self.prepared.metadata.plan_digest

    @property
    def instance(self) -> str:
        return self.prepared.identity

    def manifest(
        self,
        export_url: str,
        *,
        refresh_interval_ms: int = 1000,
    ) -> dict[str, object]:
        return prepared_view_manifest(
            self.prepared.manifest(
                export_url,
                state=self.selected_inputs,
                refresh_interval_ms=refresh_interval_ms,
            ),
            projections=self.projections,
            document_sha256=self.prepared.plan.document_sha256,
            view=self.request.snapshot.view_name,
            plan_digest=self.plan_digest,
        )


__all__ = ["PreparedView", "PreparedViewMetadata", "PreparedViewRequest"]
