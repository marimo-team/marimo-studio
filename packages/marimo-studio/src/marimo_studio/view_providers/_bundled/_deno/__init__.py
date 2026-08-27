"""Share project and Deno capabilities across framework providers.

React and Svelte use this package to render starters, identify the files shown
in Source, copy immutable build inputs, find notebook mounts, merge public
assets, locate the pinned Deno executable, and reuse its dependency cache.

Both providers therefore apply the same file limits, frozen dependency inputs,
command cancellation, and setup diagnostics. A missing or incompatible Deno
runtime is reported before a build starts with the installation guidance needed
to restore the provider.
"""

from marimo_studio.view_providers._bundled._deno.files import (
    copy_project_inputs as copy_project_inputs,
)
from marimo_studio.view_providers._bundled._deno.files import (
    project_inventory as project_inventory,
)
from marimo_studio.view_providers._bundled._deno.files import (
    template_files as template_files,
)
from marimo_studio.view_providers._bundled._deno.runtime import (
    DENO_VERSION as DENO_VERSION,
)
from marimo_studio.view_providers._bundled._deno.runtime import (
    DenoExecution as DenoExecution,
)
from marimo_studio.view_providers._bundled._deno.runtime import (
    DenoExecutionError as DenoExecutionError,
)
from marimo_studio.view_providers._bundled._deno.runtime import (
    create_execution as create_execution,
)
from marimo_studio.view_providers._bundled._deno.runtime import (
    deno_availability as deno_availability,
)
from marimo_studio.view_providers._bundled._deno.runtime import (
    deno_binary as deno_binary,
)
