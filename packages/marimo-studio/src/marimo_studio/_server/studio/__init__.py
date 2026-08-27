"""Serve the authenticated Studio authoring workspace.

The package renders the workspace document, the data needed to attach an
existing browser host, a repair page for invalid source, and a waiting page
while notebook services start. It also exposes the APIs that list, create,
inspect, and remove views and read or save their Source documents.

Source saves carry the revision the browser loaded. A conflicting edit returns
the current revision so the browser can preserve its unsaved buffer instead of
overwriting newer work.
"""

from marimo_studio._server.studio.document import (
    studio_bootstrap_payload as studio_bootstrap_payload,
)
from marimo_studio._server.studio.document import (
    studio_document as studio_document,
)
from marimo_studio._server.studio.repair import repair_document as repair_document
from marimo_studio._server.studio.waiting import waiting_document as waiting_document
