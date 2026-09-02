"""Compose the bundled Vanilla starter catalog."""

from marimo_studio.view_providers._bundled._starters import starter_catalog
from marimo_studio.view_providers._bundled.vanilla.starters.default import (
    starter as default,
)

catalog = starter_catalog(default)
