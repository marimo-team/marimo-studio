"""Build Studio metadata around one marimo-export prepared manifest."""

from __future__ import annotations

from collections.abc import Mapping

from marimo_export.manifest import prepared_manifest_bytes


def prepared_view_manifest(
    prepared: Mapping[str, object],
    *,
    projections: Mapping[str, Mapping[str, str]],
    document_sha256: str,
    view: str,
    plan_digest: str,
) -> dict[str, object]:
    """Return one bounded Studio manifest around a core prepared manifest."""
    manifest: dict[str, object] = {
        "schema": "marimo-studio.prepared.v1",
        "prepared": dict(prepared),
        "projections": {name: dict(values) for name, values in projections.items()},
        "document_sha256": document_sha256,
        "view": view,
        "plan_digest": plan_digest,
    }
    prepared_manifest_bytes(manifest)
    return manifest


__all__ = ["prepared_view_manifest"]
