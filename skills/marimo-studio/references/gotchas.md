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

**`starters()` reports Typst, Quarto, or LaTeX as unavailable.**
Typst needs the `typst` extra in the server environment. Restart the server
with `marimo-studio[typst]`. Quarto needs Quarto 1.9.38 or newer on `PATH` before
the server starts. Install it from https://quarto.org/docs/get-started/ or with
`pixi global install quarto`, then restart the server. When the reason says the
environment is not activated, Quarto comes from a pixi or conda environment
that the server started without activating. Activate that environment, for
example with `pixi shell`, then restart the server. LaTeX needs Tectonic 0.15
or newer on `PATH`. Install it with `pixi global install tectonic`, then restart
the server.

**A Studio command reports that the notebook uses a pixi workspace.**
Studio runs inside the workspace environment and never re-enters it. Run the
command the error prints, which starts `marimo-studio` through `pixi run`.

**A Typst or LaTeX view shows `render-value-not-json`.**
The document reads a value without a JSON form, such as a model object or a
figure. Read one of its fields, or a table, dictionary, list, text, number, or
date that the notebook computes. Documents read dataframes as lists of rows and
dates as ISO 8601 text, so project nothing for the document.

**A Typst or LaTeX view names an output that has no image form.**
A `marimo_output()` or `\marimographics` read targets a value without an
image form the document places, such as a table, and the view shows it beside
the document with `output-media-unavailable`. Typst places PDF, SVG, PNG, JPEG,
WebP, and GIF, and LaTeX places PDF, PNG, and JPEG. Read a figure, such as a
matplotlib figure or an Altair chart, and install `vl-convert-python` for
Altair. Studio renders matplotlib figures and Altair charts as PDF with
embedded fonts, at the width the document places them at, so the notebook
needs no output settings or page widths.

**A LaTeX build reports `latex-compile-unfinished`.**
Tectonic downloads the TeX packages a document uses on its first compile, and
that compile outlasted the build. Build the view again. Tectonic keeps what it
downloaded, so the next build continues. Run `tectonic -X compile main.tex` in
the view folder to download them without a time limit. When the build stops
again with the packages downloaded, the document never finishes compiling,
for example because of a recursive macro, so fix the document.

**A LaTeX compile fails with `is not among the values Studio supplied`.**
A marimo command reads a selector that a macro builds, such as
`\newcommand\pct[1]{\marimonum{#1}}`, so Studio never saw it. Write the
selector in full where it is read, and name repeated number settings with
`\DeclareMarimoFormat{name}{keys}`.

**A LaTeX number prints `??` or an em dash.**
`??` means Studio has no value for the read yet, for example because its
notebook cell failed, and an em dash means the value is null, including a step
through `None` such as `peak.label` while `peak` is `None`. Change them with
`\marimosetup{missing=..., null=...}` or the read's own `missing=` and `null=`
keys.

**A Typst `marimo_cell()` or LaTeX `\marimocell` read shows its default.**
The cell has not run, or its output is text, a table, or another output
without an image form. These reads place the output as marimo shows it, such
as a PNG for a cell that ends with a matplotlib figure. Read the figure's
variable with `marimo_output()` or `\marimographics` for a vector PDF.

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
A projected JSON value must encode within 1,000,000 bytes and a projected
dataframe within 64 MiB of Arrow IPC. Project tables as dataframes, filter or
aggregate them in the notebook, or split the data into per-item values and
select one at runtime, as in [projections](projections.md#select-targets).
Runtime selection needs the Python or Browser runtime.

**A value host fails with `response-too-large`.**
The values a view projects from one cell share 1,000,000 bytes of JSON and
128 MiB of Arrow, or 64 MiB of Arrow in the Browser runtime. Project fewer
values from that cell, or move large tables into separate cells.

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
