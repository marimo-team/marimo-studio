"""Compose the bundled React starter catalog."""

from marimo_studio.view_providers._bundled._starters import starter_catalog
from marimo_studio.view_providers._bundled.deno_react.starters.default import (
    starter as default,
)
from marimo_studio.view_providers._bundled.deno_react.starters.reveal import (
    starter as reveal,
)

catalog = starter_catalog(default, reveal)
