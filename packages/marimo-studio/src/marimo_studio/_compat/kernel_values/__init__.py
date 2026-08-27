"""Connect approved presentation requests to a live Marimo kernel.

Custom pages can read selected JSON values, render native Marimo output, and
synchronize public query state with the notebook. Studio resolves the requested
target and the cells needed to produce it before the request reaches the
kernel. The kernel checks that those cells still match the live notebook, so a
reconnect or source change cannot turn an old page into access to new state.

Runtime validation uses a separate temporary permission for the selectors it
is checking. Both paths return the same bounded value and output records while
the Marimo-specific queue and formatting calls remain in this package.
"""

from marimo_studio._compat.kernel_values.kernel import (
    probe_selector_lease as probe_selector_lease,
)
from marimo_studio._compat.kernel_values.models import (
    DEFAULT_MAX_VALUE_BYTES as DEFAULT_MAX_VALUE_BYTES,
)
from marimo_studio._compat.kernel_values.models import (
    FUNCTION_NAME as FUNCTION_NAME,
)
from marimo_studio._compat.kernel_values.models import (
    NAMESPACE as NAMESPACE,
)
from marimo_studio._compat.kernel_values.models import (
    OUTPUT_FUNCTION_NAME as OUTPUT_FUNCTION_NAME,
)
from marimo_studio._compat.kernel_values.models import (
    ReadValuesArgs as ReadValuesArgs,
)
from marimo_studio._compat.kernel_values.models import (
    RenderValuesArgs as RenderValuesArgs,
)
from marimo_studio._compat.kernel_values.session import (
    read_probe_values as read_probe_values,
)
from marimo_studio._compat.kernel_values.session import (
    read_session_values as read_session_values,
)
from marimo_studio._compat.kernel_values.session import (
    render_probe_outputs as render_probe_outputs,
)
from marimo_studio._compat.kernel_values.session import (
    render_session_outputs as render_session_outputs,
)
from marimo_studio._projections.runtime_records import (
    OutputRenderResult as OutputRenderResult,
)
from marimo_studio._projections.runtime_records import (
    RenderedOutput as RenderedOutput,
)
from marimo_studio._projections.runtime_records import (
    ValueReadError as ValueReadError,
)
from marimo_studio._projections.runtime_records import (
    ValueReadResult as ValueReadResult,
)
