"""Prepare one immutable Studio presentation through marimo-export."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from marimo_export import ExportRepository, PreparedExport, prepare
from marimo_export.errors import MarimoExportError
from marimo_export.progress import ProgressEvent
from marimo_export.wire import canonical_json_sha256

from marimo_studio._prepared.cleanup import attempt_cleanup
from marimo_studio._prepared.compiler import CompiledExportView, compile_export_view
from marimo_studio._prepared.errors import publication_error
from marimo_studio._prepared.manifest import prepared_view_manifest
from marimo_studio._prepared.state_space import (
    StateSpaceSource,
    load_state_space_source,
)
from marimo_studio.errors import PublicationError

if TYPE_CHECKING:
    from marimo_studio._server.presentation.service import PresentationSnapshot


@dataclass(frozen=True, slots=True)
class StaticPublication:
    prepared: PreparedExport
    projections: Mapping[str, Mapping[str, str]]
    view: str
    plan_digest: str
    state_space_source: StateSpaceSource

    @property
    def instance(self) -> str:
        return self.prepared.identity

    @property
    def document_sha256(self) -> str:
        return self.prepared.plan.document_sha256

    def manifest(self, export_url: str) -> dict[str, object]:
        return prepared_view_manifest(
            self.prepared.manifest(
                export_url,
                refresh_interval_ms=0,
            ),
            projections=self.projections,
            document_sha256=self.document_sha256,
            view=self.view,
            plan_digest=self.plan_digest,
        )

    def close(self) -> None:
        self.prepared.close()


class StaticPublicationSource(Protocol):
    def protected_root(self, notebook: Path) -> Path: ...

    def resolve(
        self,
        snapshot: PresentationSnapshot,
        *,
        timeout: float = 30.0,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> StaticPublication: ...


class _PreparedPublicationSource:
    def protected_root(self, notebook: Path) -> Path:
        del notebook
        return ExportRepository.default_path()

    def resolve(
        self,
        snapshot: PresentationSnapshot,
        *,
        timeout: float = 30.0,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> StaticPublication:
        compiled: CompiledExportView | None = None
        prepared: PreparedExport | None = None
        project = snapshot.resolved.views[snapshot.view_name].view
        state_space_source = load_state_space_source(project.root)
        try:
            compiled = _compiled_export_view(snapshot, state_space_source)
            state_space_source.require_current()
            prepared = prepare(
                snapshot.resolved.workspace.notebook,
                spec=compiled.spec,
                timeout=timeout,
                progress=progress,
            )
            state_space_source.require_current()
            projections = _projections(compiled)
            publication = StaticPublication(
                prepared=prepared,
                projections=projections,
                view=snapshot.view_name,
                plan_digest=canonical_json_sha256(
                    {
                        "inputs": list(prepared.plan.inputs),
                        "state_space": state_space_source.digest,
                        "projections": projections,
                    }
                ),
                state_space_source=state_space_source,
            )
            prepared = None
            return publication
        except BaseException as error:
            if prepared is not None:
                attempt_cleanup(error, prepared.close)
            if isinstance(error, MarimoExportError):
                raise publication_error(error, compiled, snapshot) from error
            if isinstance(error, PublicationError):
                raise
            if isinstance(error, OSError):
                raise RuntimeError(str(error)) from error
            raise


def _compiled_export_view(
    snapshot: PresentationSnapshot,
    state_space_source: StateSpaceSource,
) -> CompiledExportView:
    state_space = state_space_source.state_space
    return compile_export_view(
        snapshot.resolved,
        snapshot.view_name,
        snapshot.mounts,
        state_space=state_space,
    )


def _projections(compiled: CompiledExportView) -> dict[str, dict[str, str]]:
    return {
        "cells": dict(compiled.bindings.cells),
        "outputs": dict(compiled.bindings.outputs),
        "values": dict(compiled.bindings.values),
    }


def publication_source() -> StaticPublicationSource:
    return _PreparedPublicationSource()


__all__ = [
    "StaticPublication",
    "StaticPublicationSource",
    "publication_source",
]
