"""Construct private Marimo runtime requests behind one stable function."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from marimo_studio.errors import ProtocolError

_REQUEST_MODULES = (
    "marimo._session.requests",
    "marimo._server.models.models",
)


def instantiate_notebook_request(*, auto_run: bool) -> Any:
    """Return Marimo's notebook request for the installed supported version."""
    for module_name in _REQUEST_MODULES:
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name != module_name:
                raise
            continue
        request_type = getattr(module, "InstantiateNotebookRequest", None)
        if request_type is not None:
            return request_type(object_ids=[], values=[], auto_run=auto_run)
    raise ProtocolError("Could not locate Marimo's notebook request model")
