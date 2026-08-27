"""Serialize one runtime contract for live pages and static exports.

Server presentations, WebAssembly presentations, and exported sites receive
the same detached browser record for the selected view, runtime, notebook
mounts, permitted targets, diagnostics, URLs, and Marimo settings. Browser
packages can consume that record without knowing which Python service produced
it.

Its projection revision changes whenever the notebook behavior available to
the page changes. Moving a mount or diagnostic to another source line leaves
that execution identity stable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


def _projection_diagnostic_identity(
    diagnostic: Mapping[str, object],
) -> tuple[object, ...]:
    source = diagnostic["source"]
    if not isinstance(source, Mapping):
        raise TypeError("Projection diagnostic source must be a mapping")
    return (
        diagnostic["code"],
        diagnostic["severity"],
        diagnostic["message"],
        diagnostic["hint"],
        diagnostic["view"],
        diagnostic["projection"],
        diagnostic["target"],
        source["path"],
        diagnostic.get("siteId"),
    )


def runtime_projection_revision(
    *,
    source_revision: str,
    view: str,
    runtime_id: str,
    runtime_instance: str,
    mounts: tuple[Mapping[str, object], ...],
    projection_targets: Mapping[str, object],
    projection_policy: Mapping[str, int],
    runtime_cell_refs: Mapping[str, str],
    diagnostics: tuple[Mapping[str, object], ...],
) -> str:
    """Identify the notebook and runtime contract behind projected results."""
    identity = {
        "schema": 1,
        "sourceRevision": source_revision,
        "view": view,
        "runtime": {"id": runtime_id, "instance": runtime_instance},
        "mounts": [
            {
                "id": mount["id"],
                "kind": mount["kind"],
                "allowedTargets": mount["allowedTargets"],
            }
            for mount in mounts
        ],
        "projectionTargets": dict(projection_targets),
        "projectionPolicy": dict(projection_policy),
        "runtimeBindings": {"cellRefs": dict(runtime_cell_refs)},
        "diagnostics": [
            _projection_diagnostic_identity(diagnostic) for diagnostic in diagnostics
        ],
    }
    canonical = json.dumps(
        identity,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeConfigInputs:
    """Environment-specific values used by one browser runtime document."""

    view: str
    views: tuple[str, ...]
    runtime_id: str
    runtime_instance: str
    runtime_data: Mapping[str, object]
    root_url: str
    public_root_url: str
    document_root_url: str
    support_url: str
    projection_revision: str
    show_cell_logs: bool
    projection_targets: Mapping[str, object]
    mounts: tuple[Mapping[str, object], ...]
    projection_policy: Mapping[str, int]
    runtime_cell_refs: Mapping[str, str]
    diagnostics: tuple[Mapping[str, object], ...]
    app_config: Mapping[str, object]
    user_config: Mapping[str, object]
    config_overrides: Mapping[str, object]
    dev: bool
    mode: Literal["edit", "run"]
    presentation_session_id: str | None = None

    def to_dict(self, *, revision: str) -> dict[str, object]:
        """Return one detached runtime configuration payload."""
        payload: dict[str, object] = {
            "schema": 1,
            "revision": revision,
            "projectionRevision": self.projection_revision,
            "view": self.view,
            "views": list(self.views),
            "runtime": {
                "id": self.runtime_id,
                "instance": self.runtime_instance,
                "data": dict(self.runtime_data),
            },
            "rootUrl": self.root_url,
            "publicRootUrl": self.public_root_url,
            "documentRootUrl": self.document_root_url,
            "supportUrl": self.support_url,
            "showCellLogs": self.show_cell_logs,
            "projectionTargets": dict(self.projection_targets),
            "mounts": [dict(mount) for mount in self.mounts],
            "projectionPolicy": dict(self.projection_policy),
            "runtimeBindings": {"cellRefs": dict(self.runtime_cell_refs)},
            "diagnostics": [dict(diagnostic) for diagnostic in self.diagnostics],
            "appConfig": dict(self.app_config),
            "userConfig": dict(self.user_config),
            "configOverrides": dict(self.config_overrides),
            "dev": self.dev,
            "mode": self.mode,
        }
        if self.presentation_session_id is not None:
            payload["presentationSessionId"] = self.presentation_session_id
        return payload
