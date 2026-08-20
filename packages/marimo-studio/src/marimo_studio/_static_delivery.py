"""Prepare one Studio view through the public marimo-export SDK."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from marimo_export import ExportRepository, PreparedExport, prepare
from marimo_export.errors import MarimoExportError
from marimo_export.manifest import prepared_manifest_bytes
from marimo_export.wire import canonical_json_sha256

from marimo_studio._cleanup import attempt_cleanup
from marimo_studio._server.prepared_view_spec import (
    _compile_saved,
    _load_saved_spec,
)
from marimo_studio._server.studio.view_compiler import (
    CompiledExportView,
    compile_export_view,
)
from marimo_studio.errors import PublicationError

if TYPE_CHECKING:
    from marimo_studio._server.presentation import PresentationSnapshot


@dataclass(frozen=True, slots=True)
class StaticPublication:
    prepared: PreparedExport
    projections: Mapping[str, Mapping[str, str]]
    view: str
    plan_digest: str
    owner: PreparedExport

    @property
    def instance(self) -> str:
        return self.prepared.identity

    @property
    def path(self) -> Path:
        return self.prepared.path

    @property
    def document_sha256(self) -> str:
        return self.prepared.plan.document_sha256

    def manifest(self, export_url: str) -> dict[str, object]:
        """Return Studio metadata around one core prepared-export manifest."""

        manifest: dict[str, object] = {
            "schema": "marimo-studio.prepared.v1",
            "prepared": self.prepared.manifest(
                export_url,
                refresh_interval_ms=0,
            ),
            "projections": {
                name: dict(values) for name, values in self.projections.items()
            },
            "document_sha256": self.document_sha256,
            "view": self.view,
            "plan_digest": self.plan_digest,
        }
        prepared_manifest_bytes(manifest)
        return manifest


class StaticPublicationSource(Protocol):
    def protected_root(self, notebook: Path) -> Path: ...

    def resolve(
        self,
        snapshot: PresentationSnapshot,
        *,
        timeout: float = 30.0,
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
    ) -> StaticPublication:
        prepared: PreparedExport | None = None
        try:
            compiled = _compiled_export_view(snapshot)
            prepared = prepare(
                snapshot.resolved.workspace.notebook,
                spec=compiled.spec,
                timeout=timeout,
            )
            prepared.open().verify()
            projections = _projections(compiled)
            publication = StaticPublication(
                prepared=prepared,
                projections=projections,
                view=snapshot.view_name,
                plan_digest=canonical_json_sha256(
                    {
                        "inputs": list(prepared.plan.inputs),
                        "projections": projections,
                    }
                ),
                owner=prepared,
            )
            prepared = None
            return publication
        except BaseException as error:
            if prepared is not None:
                attempt_cleanup(error, prepared.close)
            if isinstance(error, (MarimoExportError, OSError, PublicationError)):
                raise RuntimeError(str(error)) from error
            raise


def _compiled_export_view(
    snapshot: PresentationSnapshot,
) -> CompiledExportView:
    baseline = compile_export_view(snapshot)
    saved = _load_saved_spec(snapshot)
    return baseline if saved is None else _compile_saved(snapshot, saved)


def _projections(compiled: CompiledExportView) -> dict[str, dict[str, str]]:
    return {
        "cells": dict(compiled.bindings.cells),
        "outputs": dict(compiled.bindings.outputs),
        "values": dict(compiled.bindings.values),
    }


def publication_source() -> StaticPublicationSource:
    """Construct the public SDK adapter for static prepared exports."""

    return _PreparedPublicationSource()


__all__ = [
    "StaticPublication",
    "StaticPublicationSource",
    "publication_source",
]
