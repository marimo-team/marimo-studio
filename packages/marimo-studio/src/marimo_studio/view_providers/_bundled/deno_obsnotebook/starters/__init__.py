"""Compose the Notebook Kit starter catalog."""

from marimo_studio.view_providers._bundled._starters import starter_catalog
from marimo_studio.view_providers._bundled.deno_obsnotebook.starters.default import (
    starter,
)

catalog = starter_catalog(starter)
