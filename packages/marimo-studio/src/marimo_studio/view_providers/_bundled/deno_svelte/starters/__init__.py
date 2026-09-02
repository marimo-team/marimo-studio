"""Compose the bundled Svelte starter catalog."""

from marimo_studio.view_providers._bundled._starters import starter_catalog
from marimo_studio.view_providers._bundled.deno_svelte.starters.default import (
    starter as default,
)

catalog = starter_catalog(default)
