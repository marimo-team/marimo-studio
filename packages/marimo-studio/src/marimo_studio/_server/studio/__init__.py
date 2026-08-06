"""Render Studio workspace lifecycle documents."""

from marimo_studio._server.studio.document import studio_document
from marimo_studio._server.studio.initialize import initialization_document
from marimo_studio._server.studio.repair import repair_document
from marimo_studio._server.studio.waiting import waiting_document

__all__ = [
    "initialization_document",
    "repair_document",
    "studio_document",
    "waiting_document",
]
