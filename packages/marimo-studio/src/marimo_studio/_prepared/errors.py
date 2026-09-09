"""Preserve export failure context for live previews, static exports, and agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from marimo_export.errors import (
    CaptureLimitError,
    CompatibilityError,
    MarimoExportError,
    OutputError,
    SessionError,
    SpecError,
    TransportError,
)
from marimo_export.repository import RepositoryLimitError

from marimo_studio._prepared.compiler import CompiledExportView
from marimo_studio.errors import PublicationError, PublicationLimitError

if TYPE_CHECKING:
    from marimo_studio._server.presentation.service import PresentationSnapshot


def _recovery_hint(error: MarimoExportError) -> str:
    if isinstance(error, CompatibilityError):
        return (
            "Check the installed Marimo and marimo-export versions, "
            "then restart Studio."
        )
    if isinstance(error, (SessionError, TransportError)):
        return (
            "Confirm that the notebook is open and its server is reachable, "
            "then retry the preview."
        )
    if isinstance(error, SpecError):
        return "Check the view projections and configured notebook states, then retry."
    return (
        "Inspect the reported notebook output and state. "
        "Fix the input or select Python or Browser in Studio."
    )


def _projection_identity(
    compiled: CompiledExportView | None,
    output: object,
) -> tuple[str, str] | None:
    if compiled is None or not isinstance(output, str):
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


def publication_error(
    error: MarimoExportError,
    compiled: CompiledExportView | None,
    snapshot: PresentationSnapshot,
) -> PublicationError:
    wire = error.wire()
    details = error.details
    if isinstance(error, (CaptureLimitError, RepositoryLimitError)):
        return PublicationLimitError(
            str(error),
            details={"runtime": "zero-python", "marimo_export": wire},
            hint=(
                "Reduce the number of prepared states or the size of projected "
                "outputs, then retry."
            ),
        )
    identity = _projection_identity(compiled, details.get("output"))
    identities = (
        _projection_identities(compiled)
        if compiled is not None
        else tuple(
            dict.fromkeys(
                (site.kind, target)
                for site in snapshot.mounts
                for target in site.allowed_targets or ()
            )
        )
    )
    if identity is None and len(identities) == 1 and isinstance(error, OutputError):
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
                    "Prepared cannot display this notebook output because it calls "
                    "Python functions."
                ),
                code="zero-python-projection-functions",
                details=diagnostic,
                hint=(
                    "Select Python or Browser in Studio, or export with WebAssembly. "
                    "To use Prepared, project serializable data "
                    "or a portable notebook output."
                ),
            )
        return PublicationError(
            f"Could not prepare the notebook states: {error}",
            code=error.code,
            details=diagnostic,
            hint=_recovery_hint(error),
        )
    kind, target = identity
    diagnostic.update(_projection_details(snapshot, identity))
    if isinstance(functions, list) and functions:
        return PublicationError(
            (
                f"Prepared cannot display {kind} projection {target!r} because "
                "its notebook output calls Python functions."
            ),
            code="zero-python-projection-functions",
            details=diagnostic,
            hint=(
                "Select Python or Browser in Studio, or export with WebAssembly. "
                "To use Prepared, project serializable data "
                "or a portable notebook output."
            ),
        )
    return PublicationError(
        f"Could not prepare {kind} projection {target!r}: {error}",
        code=error.code,
        details=diagnostic,
        hint=_recovery_hint(error),
    )
