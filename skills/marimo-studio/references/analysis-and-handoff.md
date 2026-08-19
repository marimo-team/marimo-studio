# Analysis and handoff

Studio analysis binds validation to one saved source revision. Static checks
read the notebook graph and view files. Runtime checks execute the projected
dependency closure in an isolated process. Browser checks confirm that a
connected Studio tab rendered the current revision and report projection,
presentation, host, and runtime diagnostics.

## Activate the view

Code mode targets the Studio browser attached to its current Marimo session:

```python
setup = studio.ensure_view(ctx, "dashboard")
activation = await studio.activate_view(ctx, setup.name)
```

Activation selects Build so the notebook and preview share the workspace. When
the requested view is already active, Studio starts a reload of every prepared
preview runtime before acknowledging the activation. The reload clears the
current ready revision and diagnostics until each frame reports its new state.
Call `activate_view` again when the visible page looks stale or stuck, then run
focused analysis in the next code-mode call.

An active Studio workspace acknowledges its in-place transition. Creating the
first view opens the Build workspace around the existing native editor, so the
code-mode call stays connected until the browser acknowledges activation.

A regular agent activates a view through the running server:

```console
MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
marimo-studio view activate analysis.py \
  --name dashboard \
  --format json
```

Pass `--browser-client ID` or `MARIMO_STUDIO_BROWSER_CLIENT` when several
Studio tabs are connected. With no ID, activation succeeds when exactly one
browser is connected. The result contains the selected `client_id`, bound
`session_id`, transition, and generation.

| Activation code                 | Recovery                                                     |
| ------------------------------- | ------------------------------------------------------------ |
| `view-not-found`                | Read `overview` and select a configured view                 |
| `browser-client-ambiguous`      | Pass the intended browser client ID                          |
| `browser-client-unavailable`    | Open or reconnect the intended Studio tab                    |
| `browser-session-unavailable`   | Wait for the tab's Marimo editor session to connect          |
| `browser-operation-in-progress` | Wait for the current browser operation, then retry           |
| `activation-timeout`            | Inspect the selected tab and retry after it finishes loading |
| `notebook-mismatch`             | Use the server URL for the target notebook                   |
| `protocol-error`                | Align the installed Studio client and server versions        |

## Analyze and repair

Run focused code-mode analysis after activation finishes and the selected view
loads:

```python
report = await studio.analyze(
    ctx,
    view="dashboard",
    browser_timeout=10,
    runtime_timeout=120,
)
for action in report.actions:
    print(action.stage, action.code, action.advice)
```

Each successful browser observation includes a structured `runtime_status`
report. Read `current` for the active phase and diagnostics. Read
`transitions` when a brief connection or diagnostic state has already cleared:

```python
observation = report.browser_observations[0]
status = observation.runtime_status
if status is not None:
    print(status.current.phase)
    for transition in status.transitions:
        print(transition.sequence, transition.phase)
```

Code mode analyzes one active browser view at a time. Activate and analyze each
changed view in separate calls. Set `require_browser=False` to collect static
and isolated runtime evidence without the browser handoff requirement.

Run the same handoff gate from the CLI:

```console
MARIMO_STUDIO_SERVER_URL=http://localhost:2718 \
MARIMO_STUDIO_ACCESS_TOKEN="$STUDIO_TOKEN" \
marimo-studio analyze analysis.py \
  --view dashboard \
  --browser-timeout 10 \
  --runtime-timeout 120 \
  --format json \
  --diagnostics jsonl
```

The external CLI may omit `--view` and visit every configured view because it
does not hold the notebook kernel while Studio switches views. Pass
`--no-browser` for a source and runtime gate whose successful result can become
handoff-ready without rendered evidence.

Both timeouts accept finite values from 0 through 300 seconds. A
`runtime-timeout` action means the notebook did not settle within the selected
runtime budget. Increase the budget for expected setup work or repair the
operation that did not finish.

Analysis executes notebook code and can perform its configured file, network,
database, and data access. Run it in the notebook environment.

## Use the repair queue

`AnalysisReport.actions` contains ordered records with a stage, severity,
stable code, message, advice, and available view, target, or source location.
Fix one cause, save the source, rerun the same analysis, and continue until the
queue is empty and `handoff_ready` is true.

| Problem                                 | Repair                                                   |
| --------------------------------------- | -------------------------------------------------------- |
| Cell name is missing                    | Use a current native name or bind the intended cell      |
| Saved cell alias is stale or ambiguous  | Reinspect and bind the intended cell with `--overwrite`  |
| Python value reference is unknown       | Correct its root variable or nested path                 |
| Python value fails during execution     | Inspect the defining cell and its current output         |
| View files are missing                  | Create the configured default view                       |
| Browser evidence is stale               | Wait for the saved revision to render and rerun analysis |
| Visible page is stale with ready status | Reactivate the view, then rerun focused analysis         |
| Browser selection is ambiguous          | Pass the intended `--browser-client`                     |

A static or runtime pass cannot prove that the current browser read the saved
view revision. Keep browser evidence required for final agent handoff.

## Inspect the live result

After analysis passes, confirm:

- The first screen supports the named audience and task.
- Every projected cell, rich object, and value finishes loading.
- Controls, tables, plots, downloads, and anywidgets remain interactive.
- Notebook edits update dependent content.
- HTML, CSS, and JavaScript edits refresh from disk.
- Loading placeholders reserve stable space.
- Narrow and wide layouts remain readable and operable.
- Light and dark appearance preserve readable contrast.
- Keyboard focus and control labels remain visible.

## Serve or export

Serve configured views through Marimo:

```console
marimo run analysis.py --sandbox --headless
```

The default view is available at `/`. A view named `report` is available at
`/report/`. Each browser receives its own Python kernel session.

Export one WebAssembly-compatible view:

```console
marimo-studio export analysis.py \
  --view report \
  --output dist/report \
  --format json \
  --diagnostics jsonl
```

Run runtime validation before export. Use `--force` after reviewing an existing
destination that should be replaced. Edit notebook or view source for later
changes, then export again.

## Handoff record

Run focused analysis immediately before handoff. Repair the ordered actions and
repeat until `handoff_ready` is true, then inspect the live result. Reactivate
and recheck a page that remains stale or broken after the first pass.

Report:

- notebook path and changed view names
- audience and primary task for each view
- HTML, CSS, JavaScript, and relative assets changed
- cell aliases and Python value references used
- configuration changes
- static, runtime, and browser evidence
- interactions, loading states, widths, and color modes inspected

Leave the notebook and every changed view runnable with no reported errors.
