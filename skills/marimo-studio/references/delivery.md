# Run and export

Choose before designing controls or exposing data:

| Runtime                     | Interaction                                                                             | Privacy boundary                                                                                                             |
| --------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Server (`server`)           | Python computes new states using server packages and services                           | Source and credentials stay on the server. Projected outputs reach visitors.                                                 |
| WASM (`wasm`)               | Pyodide computes new states in the visitor's browser                                    | Visitors receive notebook source and browser-accessible data. Never embed secrets.                                           |
| Zero-Python (`zero-python`) | Visitors select finite prepared states, with browser-only interaction on published data | Python runs during preparation. Visitors receive prepared outputs and public files, including states they have not selected. |

Static export defaults to Zero-Python. Choose WASM explicitly when visitors
need unprepared states and the notebook supports Pyodide. Use Server for
interactions that need private services or native Python packages. The editor
can preview all three runtimes. A live `marimo run` serves Server or WASM.

## Prepare the delivery

Run through marimo when the notebook needs Python packages, local files,
databases, or server credentials:

```python
status = await workspace.status()
print(status.launch_requirements)
```

Check dependency consistency in the notebook's environment before validation
or export:

```console
marimo-studio doctor --dependencies --target notebook.py --json
```

Read its interpreter path, declaration drift, provider requirements, and import
availability. It inspects imports without executing notebook cells. Preserve
project-managed execution with `uv run --project <root>` and `--no-sandbox`.
Use `--sandbox` when the notebook's PEP 723 dependencies own execution.
See [setup](setup.md#check-missing-capabilities) to interpret declaration drift
separately from missing imports.

Pass every exact requirement through the environment tool. A standalone
notebook whose only provider is the default Vanilla provider runs with:

```console
uv run --with marimo-studio marimo run notebook.py --sandbox
```

Preflight the intended static runtime before publishing:

```console
marimo-studio view preflight dashboard \
  --target notebook.py \
  --runtime zero-python \
  --json
```

Read every projection portability record and delivery diagnostic. Zero-Python
must verify finite projection targets across the configured input states. Use
WebAssembly when visitors must recompute unprepared states and the notebook can
run through Pyodide.

For Zero-Python controls, configure `states.yaml` in the selected view project.
An omitted state file prepares the initial notebook state. Keep presentation-only
copy in view source. A Python label edit changes notebook publication identity
and requires another state walk, even if native cell caching avoids recomputation.
Use explicit state rows when valid combinations are sparse. Keep browser-only
filtering of projected data in the view. A matrix prepares every combination
of its input choices.

A prepared state records every control in the notebook graph, including
controls a view never shows. Visitors change controls without Python, so a
control that Python recreates from another control, such as a widget seeded
from a preset, keeps its previous value and the combination matches no prepared
state. Make each prepared control an independent input, and derive the dependent
values in Python.

The state walk can restore a cell whose inputs did not change from Marimo's
cache. The cache restores each definition of that cell separately, so objects
that must stay shared, such as a CVXPY problem and the `Parameter` a function
assigns before solving, return as independent copies. Build those objects inside
the function that uses them, then preflight every state.

Prepared state values use each control's **frontend value**, which can differ
from its Python `.value`. A dropdown takes a one-item array of its option label,
a radio takes its option label, a multiselect takes an array of labels, and a
slider takes a number. For a
`scenario` dropdown with labels `Overview` and `Reviewed` and a
`minimum_magnitude` slider, put this in the selected view's `states.yaml`:

```yaml
schema: marimo-export.states.v1
default_state: overview
states:
  overview:
    scenario: [Overview]
    minimum_magnitude: 2.5
  reviewed:
    scenario: [Reviewed]
    minimum_magnitude: 4.0
```

State keys name the notebook control variables. For dropdown options that map
labels to Python objects, use the label array rather than the mapped object.
Preflight this file before export and exercise every offered state in the
exported browser view.

A Prepared preview that reports `parent_document_changed` after the notebook's
dependencies changed is comparing a running document with a saved file that
moved on. Restart the notebook, then preview again.

Export the verified runtime:

```console
marimo-studio view export dashboard \
  --target notebook.py \
  --runtime zero-python \
  --output dist/dashboard
```

Use `--runtime wasm` on both commands for a WASM export.

Export runs the same preflight before committing its destination. Progress is
written to stderr, including marimo-export prepared-state reuse and cache
activity. Each progress record names its owning source and nests that owner's
event. With `--json`, stdout remains one terminal result and stderr contains
JSON Lines progress and diagnostics. Events are flushed during environment
re-entry. Five-second heartbeats report the phase, state, elapsed time, and
latest cache evidence. Unavailable state, cache, or active-cell evidence is
`null`.

Zero-Python keeps Python source on the build machine and publishes prepared
outputs. WebAssembly includes saved notebook source for browser execution.
Review public files, data URLs, authored browser code, and remote dependencies
before publishing.

Serve the completed export over HTTP and exercise its controls and projected
results. Verify a failed state selection retains the preceding display when
the view includes recovery behavior. A live preview and an exported view need
their own runtime evidence.
