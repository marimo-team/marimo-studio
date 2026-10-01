# Recover from common failures

Read when a Studio command, build, or browser check fails, or when a result
looks different from the source you wrote. Each entry starts with what you
observe, then gives the cause and the next step.

## Launch and environment

**`CompatibilityError: Studio requires the published marimo <version> release`.**
Studio requires the exact marimo release named in the message. Launch that
release with the command in
[Bind to the intended notebook](../SKILL.md#bind-to-the-intended-notebook).

**`starters()` reports React, Svelte, Reveal.js, or Notebook Kit as unavailable.**
The server environment lacks the `deno` extra. Restart the server with
`marimo-studio[deno]`. Starting every session with the `deno` extra avoids
this restart.

**The editor reports that `index.html` is missing after hours of work.**
A `uvx` server runs from uv's cache. Cleaning or pruning that cache deletes the
running server's static files. Restart the server.

## Code mode

**`RuntimeWarning: coroutine ... was never awaited`.**
Methods on workspace and view handles, such as `status()`, `build()`,
`show()`, and `preview_url()`, are coroutines. Await each call.
`current_workspace()` and `workspace.view()` return handles directly.

**`No running session for notebook ...` from `marimo pair`.**
A headless server starts a notebook's kernel when a browser opens it. Open the
notebook's editor URL, such as `http://localhost:2718/?file=notebook.py` for a
folder server, then retry. Keep that tab open while you work.

**Variables or view handles disappear between executions.**
Each `pair execute` runs in a fresh scratchpad. Reacquire handles as in
[Bind to the intended notebook](../SKILL.md#bind-to-the-intended-notebook),
and read a publication hold back as in [authoring](authoring.md).

## Views

**`LastViewError: Studio keeps at least one view`.**
To change a name, rename the view. To replace a view, create and show
the replacement, then remove the old view, as in
[Select or create the view](../SKILL.md#select-or-create-the-view). Removing
the default view promotes the first remaining view to default.

**`view-in-use` from `marimo-studio view remove` or `view rename`.**
A running Studio server holds that view's artifacts. Remove or rename it from
code mode in that notebook, for example with
`await workspace.view("<name>").rename("<new-name>")`.

**`PublicationHeldError` or `publication-held` from `hold_publication()` or a view rename.**
Another publication hold is active on that view. Release it with its token as
in [authoring](authoring.md), or wait for the expiry named in the message.

**The starter lists targets such as `cell-1`, `cell-4`, and `cell-10`.**
Starters place every displayable cell and bind a `cell-N` alias for each
anonymous one. Replace those targets with names from the notebook. Name a cell
with `ctx.edit_cell(cell_id, name="summary")` when the name belongs in the
notebook, or bind an alias with `workspace.bind()`.

**A build fails with `path:line:column: message. Inspect the view to list 2 more diagnostics.`**
The exception carries the first diagnostic. Read every diagnostic of the
development build before editing:

```python
inspection = await view.inspect()
for item in inspection.latest_build.diagnostics:
    where = item.source and f"{item.source.path}:{item.source.line}:{item.source.column}"
    print(item.code, where or "view.toml", item.message, item.hint)
```

**`module-path-outside-project` when views import a shared component.**
A view builds from files inside its own project. Copy the component into each
view that uses it, and rebuild every view after changing a copy.

## Verification

**`No Studio tab is connected to this notebook session`, or a preview waiting for `the Studio tab this preview follows`.**
A server preview follows the Studio tab connected to the notebook session.
Open or reload the notebook in Studio, then request a new preview URL.

**The page is blank and `data-marimo-studio-state` is `error`.**
A view script threw. The page shows the built file and position, such as
`main.js:2:23: TypeError: <message>`, or `inline script` for a module script
inside the HTML document. `marimoStudio.diagnostics()` lists it with the `view-script-error`
code. Fix the view source, build the view, then reload the page.

**Browser automation in the Studio tab cannot read the view.**
The Studio tab renders the view in a sandboxed frame. Use frame-aware
automation, or open the view's preview URL as in
[verification](verification.md).

**`ScreenshotError: Playwright is not installed.` from marimo code mode.**
marimo's `ctx.screenshot()` from `marimo._code_mode` captures one notebook
cell's output and needs Playwright in the kernel environment. Capture a view
by opening its preview URL with an external browser tool.

**Projected output still shows old content after a restart.**
marimo can restore cells as stale. Run stale cells in the live notebook before
checking projected output.

## Data in views

**A value host fails with `value-too-large`.**
Each projected value must encode within 1,000,000 bytes. Split the data into
per-item values and select one at runtime, as in
[projections](projections.md#select-targets). Runtime selection needs the
Python or Browser runtime.

**A click in custom view code needs to change a notebook computation.**
Route the change through a native marimo control, as in
[projections](projections.md#select-targets).

**`projection-target-not-allowed` after changing `mo-value` at runtime.**
The host lacks `data-marimo-allow="*"`, so its mount accepts its authored
selector alone. Add the wildcard to every host whose selector changes in the
browser.

## Share a result

**`marimo export html` writes the notebook page when a view was expected.**
Export the Studio view with `marimo-studio view export`, or
`await view.export(path, runtime=...)` in code mode, after choosing the
runtime in [delivery](delivery.md). Serve the output directory over HTTP.
