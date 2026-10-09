"""List the built-in React starters."""

from marimo_studio.view_providers._builtin.deno_react.starters.default import (
    starter as default,
)
from marimo_studio.view_providers._builtin.deno_react.starters.reveal import (
    starter as reveal,
)

STARTERS = (default, reveal)
