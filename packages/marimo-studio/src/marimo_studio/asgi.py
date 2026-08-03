"""Environment-configured ASGI entry point for application servers."""

from __future__ import annotations

import os

from marimo_studio import create_asgi_app

notebook = os.environ.get("MARIMO_STUDIO_NOTEBOOK")
if notebook is None:
    raise RuntimeError("MARIMO_STUDIO_NOTEBOOK must point to a configured notebook")

app = create_asgi_app(notebook)
