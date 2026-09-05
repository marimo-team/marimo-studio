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
    _repository: ExportRepository

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
        try:
            self.prepared.close()
        except BaseException as error:
            attempt_cleanup(error, self._repository.close)
            raise
        self._repository.close()


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
        repository: ExportRepository | None = None
        project = snapshot.resolved.views[snapshot.view_name].view
        state_space_source = load_state_space_source(project.root)
        try:
            compiled = _compiled_export_view(snapshot, state_space_source)
            state_space_source.require_current()
            repository = ExportRepository.open()
            prepared = prepare(
                snapshot.resolved.workspace.notebook,
                spec=compiled.spec,
                repository=repository,
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
                _repository=repository,
            )
            prepared = None
            repository = None
            return publication
        except BaseException as error:
            if prepared is not None:
                attempt_cleanup(error, prepared.close)
            if repository is not None:
                attempt_cleanup(error, repository.close)
            if isinstance(error, MarimoExportError):
                if compiled is not None:
                    raise _publication_error(error, compiled, snapshot) from error
                raise PublicationError(
                    f"Could not inspect the Zero-Python publication: {error}",
                    details={
                        "runtime": "zero-python",
                        "marimo_export": error.wire(),
                    },
                    hint="Fix the reported notebook export input and rerun preflight.",
                ) from error
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


def _projection_identity(
    compiled: CompiledExportView,
    output: object,
) -> tuple[str, str] | None:
    if not isinstance(output, str):
        return None
    for kind, bindings in (
        ("cell", compiled.bindings.cells),
        ("output", compiled.bindings.outputs),
        ("value", compiled.bindings.values),
    ):
        for target, name in bindings.items():
            if name == output:
                return kind, target
    return None


def _projection_identities(
    compiled: CompiledExportView,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (kind, target)
        for kind, bindings in (
            ("cell", compiled.bindings.cells),
            ("output", compiled.bindings.outputs),
            ("value", compiled.bindings.values),
        )
        for target in bindings
    )


def _projection_details(
    snapshot: PresentationSnapshot,
    identity: tuple[str, str],
) -> dict[str, object]:
    kind, target = identity
    return {
        "projection": kind,
        "target": target,
        "sources": [
            site.source.to_dict()
            for site in snapshot.mounts
            if site.kind == kind
            and site.allowed_targets is not None
            and target in site.allowed_targets
        ],
    }


def _publication_error(
    error: MarimoExportError,
    compiled: CompiledExportView,
    snapshot: PresentationSnapshot,
) -> PublicationError:
    wire = error.wire()
    details = error.details
    identity = _projection_identity(compiled, details.get("output"))
    identities = _projection_identities(compiled)
    if identity is None and len(identities) == 1:
        identity = identities[0]
    diagnostic: dict[str, object] = {
        "runtime": "zero-python",
        "marimo_export": wire,
    }
    functions = details.get("functions")
    if identity is None:
        if isinstance(functions, list) and functions:
            diagnostic["projections"] = [
                _projection_details(snapshot, candidate) for candidate in identities
            ]
            return PublicationError(
                (
                    "Zero-Python cannot replay a projected UI because it exposes "
                    "Python functions."
                ),
                code="zero-python-projection-functions",
                details=diagnostic,
                hint=(
                    "Project serializable data for a browser-native view, use a "
                    "portable Marimo output, or select the WebAssembly runtime."
                ),
            )
        return PublicationError(
            f"Could not prepare the Zero-Python publication: {error}",
            code=error.code,
            details=diagnostic,
            hint="Fix the reported notebook state or choose another static runtime.",
        )
    kind, target = identity
    diagnostic.update(_projection_details(snapshot, identity))
    if isinstance(functions, list) and functions:
        return PublicationError(
            (
                f"Zero-Python cannot replay {kind} projection {target!r} because "
                "its rendered UI exposes Python functions."
            ),
            code="zero-python-projection-functions",
            details=diagnostic,
            hint=(
                "Project serializable data for a browser-native view, use a portable "
                "Marimo output, or select the WebAssembly runtime."
            ),
        )
    return PublicationError(
        f"Zero-Python could not prepare {kind} projection {target!r}: {error}",
        code="zero-python-projection-failed",
        details=diagnostic,
        hint=(
            "Inspect the projected notebook result and prepared state, or select "
            "the WebAssembly runtime."
        ),
    )


def publication_source() -> StaticPublicationSource:
    return _PreparedPublicationSource()


__all__ = [
    "StaticPublication",
    "StaticPublicationSource",
    "publication_source",
]
