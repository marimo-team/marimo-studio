---
name: marimo-studio
description: >-
  Turn a Marimo notebook into focused web views. Use when an agent needs to
  inspect notebook and view source, edit a view safely, build it, show it in
  Studio, validate the rendered result, run it, or export it.
---

# Author Marimo Studio views

## Start with the installed workflow

At the start of every Studio task, run `help(marimo_studio.agent)` in the
notebook's Python environment, including when another copy of this skill is
already available:

```python
import marimo_studio.agent

help(marimo_studio.agent)
skill = marimo_studio.agent.agent_skill()
print(skill.body)
print(skill.tree())
```

The help exposes the current installed API and its packaged skill as a
traversable Python object. Follow that version-matched skill body and traverse
its bundled resources as needed. Repeat discovery when the notebook environment
or installed Studio version changes. Once this installed body is loaded,
continue with the workflow.

## Choose the delivery runtime

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
Follow [Run or export](#run-or-export) to configure, preflight, and verify the
chosen delivery.

## Preserve notebook traceability

Apply these conventions while authoring every view, even when Lens is not
installed, so adding Lens exposes named targets and their source context.
Keep metadata on authored regions and projection hosts, outside native Marimo
output subtrees.

NEVER hardcode notebook-derived values in view HTML or source code when they
can be expressed with `mo-value`, `marimo-output`, or `marimo-cell`. This includes
metrics, counts, dates, categories, chart data, and analytical claims embedded in
prose. Copied values go stale and sever the link to their analytical context.
Expose missing results as named notebook values, then project them. Static UI
copy and design constants may remain literal.

Use `mo-value` for values, `marimo-output` for rich values, and `marimo-cell`
for native cell output. Keep analytical computation in the notebook. Custom
JavaScript rendering must consume live projections, handle their updates, and
declare every kernel input:

- Place hidden `mo-value` hosts directly inside the result, or use
  `data-marimo-lens-inputs="rows-data summary-data"` to reference projection hosts by
  unique, stable HTML IDs in the same document. Include every input, including
  shared inputs used through JS transforms. References must point directly to
  mounted `mo-value`, `marimo-output`, or `marimo-cell` hosts. Missing or duplicate
  IDs make the result unavailable to Lens. Never fabricate runtime metadata.
- Annotate individual metrics, rows, charts, and report pages. Prefer narrow
  selectors such as `summary.events`. Bind dynamic selectors and source IDs to
  the state that renders the result. Use `data-marimo-allow="*"` for selectors
  the provider cannot bound at build time. Unbounded selectors require Python
  or Browser runtime (`--runtime wasm` for export). Prepared exports need finite
  authored targets.
- Link browser-only aggregates to their actual kernel inputs and label the
  browser calculation. Canvas and PDF picking is limited to the chart or page
  unless the renderer supplies finer DOM targets.
- Set `aria-busy="true"` during asynchronous rendering and clear it on completion.
  Verify selection and producer context after data updates. These links declare
  dependencies, not automatic JS dataflow or historical values.
- Studio supplies native projection labels. Give custom regions a
  `data-marimo-lens-label` and optional `data-marimo-lens-detail`. Display text
  supplements the source links that connect results to the analytical graph.
- Give custom regions a `data-marimo-lens-render-source` JSON reference with
  their actual project-relative source `path` and optional `symbol`. Keep it
  current as source moves. Use `data-marimo-lens-context` on a chart, card, or
  section when it defines the intended image context for selections.

## Activate the first view immediately

When the user requests their first view and Studio has no configured views or
active preview, make visible activation the first milestone. Create a view
named for the request, build its starter, and call `show()` in the immediately
following code-mode execution. The user should see Studio open with their new
view while the rest of the work develops.

Do substantial data exploration, analysis expansion, custom layout, and styling
after that first visible result. Refine in small visible steps through edit,
build, show, and verification. Keep each authoring call bounded to a coherent
source change.

Inspect configured views before creating one:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
status = await workspace.status()
if any(item.name == "dashboard" for item in status.views):
    view = workspace.view("dashboard")
else:
    view = await workspace.create_view("dashboard")
await view.build()
```

Use the user's requested name and frontend starter when specified. Otherwise,
the default starter produces an editable HTML document populated with enabled
cells that may display output, including literal Markdown, and project-specific
agent instructions. Inspect installed starters when selecting a requested
frontend.

Run `show()` in the next execution so the Studio tab can finish the transition:

```python
import marimo_studio.agent as studio_agent

await studio_agent.current_workspace().view("dashboard").show()
```

`show()` returns `client_id`, `preview_url`, and `frame_selector` for the
acknowledged preview. Use that exact selector for browser frame switching and
DOM evaluation. Cached and hidden frames are outside this selector.
For a standalone browser test, open the public view URL with
`?marimo_studio_unframed=1`, preserving `file` and `runtime` when present
(for example `/dashboard/?file=notebook.py&marimo_studio_unframed=1`). This
renders the view in the top-level document for screenshots and DOM evaluation.
It creates a separate presentation, retains the document sandbox, and requires
the server's usual authentication. In edit mode, keep the notebook session open. Call
`show()` again after changing the view, runtime, or browser session.

Reimport `marimo_studio.agent` and reacquire the workspace and view in each
code-mode execution. Scratch imports and handles from a preceding execution
may be gone. If build or activation fails, repair the reported problem and
retry that milestone before expanding the view.

## Keep notebook and view ownership clear

The notebook computes. The view presents. Studio connects them.

Keep data access, transformations, controls, and reusable results in notebook
cells. Keep view structure, wording, styles, and browser interaction in view
source. Each named frontend project is a view.

## Inspect before editing

Inspect the notebook before changing data, computation, controls, or reusable
results:

```python
notebook = await workspace.inspect_notebook()
```

For a change to one result, include the cells that produce its inputs:

```python
producer = await workspace.inspect_notebook(
    selectors=("summary",),
    include_code=True,
    context="upstream",
)
```

Inspect the view to discover the files Studio exposes:

```python
inspection = await view.inspect()
for document in inspection.documents:
    print(document.path, document.language, document.access)
```

Read `AGENTS.md` when the selected project exposes it:

```python
if any(document.path.as_posix() == "AGENTS.md" for document in inspection.documents):
    instructions = await view.read("AGENTS.md")
    print(instructions.content)
```

The Studio skill owns notebook boundaries, projection semantics, view lifecycle,
and validation. The starter's `AGENTS.md` owns its opinionated frontend
structure, supplied adapters, preferred libraries, and build-specific
conventions. Read both before editing a starter project.

Treat the generated `AGENTS.md` as durable project context. Update it as the
conversation establishes the audience, analytical goal, concrete domain details,
aesthetic direction, interaction priorities, framework or library preferences,
and other decisions that should guide later agents. Keep transient task status
and short-lived implementation notes out of it.

## Author Python notebook analysis

For dataset work, keep the notebook markdown-led and reactive. Build named
dataframe results that a Studio view can present or consume.

### Pair one explanation with one analytical cell

Introduce each analytical question with a short markdown cell. Put one focused
Python cell directly after it. The Python cell should derive one well-defined
table, metric, model input, or visualization input from an upstream dataset.

Each fenced block represents one notebook cell:

```python
mo.md("""
## Revenue by segment

Aggregate valid revenue rows so the view can compare segments directly.
""")
```

```python
segment_summary = (
    orders.lazy()
    .filter(pl.col("revenue").is_not_null())
    .group_by("segment")
    .agg(pl.sum("revenue").alias("revenue"))
    .sort("revenue", descending=True)
    .collect()
)
segment_summary
```

The assignment makes `segment_summary` available to downstream cells. The final
expression renders the dataframe as this cell's output. Prefer Polars
expressions for dataframe-native transformations. Use DuckDB when the operation
is clearer as SQL, then materialize a dataframe at the same cell boundary:

```python
segment_summary_sql = duckdb.sql("""
    SELECT segment, SUM(revenue) AS revenue
    FROM orders
    WHERE revenue IS NOT NULL
    GROUP BY segment
    ORDER BY revenue DESC
""").pl()
segment_summary_sql
```

### Keep the reactive dataflow legible

- Load or receive the base dataset once, then derive named results downstream.
- Give each cell one semantic responsibility and one principal result. Separate
  filtering, aggregation, enrichment, modeling, and presentation inputs when
  they answer different questions.
- Prefer expression-based transformations over in-place mutation. Materialize a
  Polars or DuckDB result when the cell establishes a reusable dataframe
  boundary.
- Use domain names such as `filtered_orders`, `segment_summary`, and
  `retention_by_month`. Reserve underscore-prefixed values for cell-local
  helpers.
- Put the dataframe, chart, control, or other intended result in the final
  expression. Keep diagnostic dumps and large unbounded previews out of the
  analytical flow.
- Keep the graph acyclic. Define each shared variable once and let downstream
  cells react to it.

### Parameterize dimensions with Marimo controls

Create a control in one cell, display it as that cell's final expression, and
read its `.value` from downstream transformation cells. Choose the control from
the dimension's datatype and selection semantics:

| Dimension                                 | Marimo control                                     |
| ----------------------------------------- | -------------------------------------------------- |
| One value from a small categorical domain | `mo.ui.dropdown`                                   |
| Several categorical values                | `mo.ui.multiselect`                                |
| Ordered numeric value or interval         | `mo.ui.slider` or `mo.ui.range_slider`             |
| Exact numeric input                       | `mo.ui.number`                                     |
| Date, datetime, or date interval          | `mo.ui.date`, `mo.ui.datetime`, `mo.ui.date_range` |
| Boolean choice                            | `mo.ui.switch` or `mo.ui.checkbox`                 |

Derive options, bounds, and defaults from the dataframe when practical. Keep the
control label tied to the analytical dimension. For example, use one control
cell and one dependent dataframe cell:

```python
segment = mo.ui.dropdown.from_series(orders["segment"], label="Segment")
segment
```

```python
selected_orders = (
    orders
    if segment.value is None
    else orders.filter(pl.col("segment") == segment.value)
)
selected_orders
```

## Author Studio view files

Edit source with Studio's guarded writes or the environment's filesystem
tools. Use `inspection.root` as the project root. Studio writes require a
catalog document with `access="edit"`. Provider inspection owns source discovery
and build inputs for either editing path. Keep generated `.artifacts/` files
under Studio's ownership. Use view files for structure, wording, styles, and
browser interaction.

`studio-view` sets a maximum width and page padding. Mount a component that
defines its own page layout in a plain `<div id="app-shell"></div>`.

### Edit the selected provider's source

Use `view.inspect()` and the project's `AGENTS.md` to choose files before
editing. Bundled starters use these entry points:

| Provider                | Page source                       | Styles                           |
| ----------------------- | --------------------------------- | -------------------------------- |
| Vanilla                 | `index.html`                      | Inline CSS or linked project CSS |
| React                   | `src/App.tsx`                     | `src/style.css`                  |
| Svelte                  | `src/App.svelte`                  | `src/style.css`                  |
| Observable Notebook Kit | `src/index.html`, `src/page.tmpl` | `src/style.css`                  |

React, Svelte, and Notebook Kit use Deno configuration and a frozen
`deno.lock`. Run dependency changes from the view root with
`deno add --frozen=false --save-exact <package>`, preserve the project's
minimum dependency age, and commit `deno.json` and `deno.lock` together.
Use `view.build()` to check the selected provider's types and build inputs.

### Choose visual direction

Choose visual direction in this order:

1. Follow the user's explicit style direction.
2. Follow the starter project's `DESIGN.md` when it exists.
3. Otherwise suggest and use Marimo's visual style from
   [Marimo's `DESIGN.md`](https://raw.githubusercontent.com/marimo-team/marimo/refs/heads/main/DESIGN.md).
   Name this file explicitly when explaining the chosen design. Use another
   design whenever the user requests it.

Read the selected design source before visual authoring. Apply its visual
character, tokens, typography, surfaces, component treatment, and motion
guidance so the selected direction shapes the whole view.

### Keep view source maintainable

Treat agent-authored view source as maintained application code. A person should
be able to inspect it, understand its analytical flow, and change it from the
source and project context alone.

- Structure code as focused, composable components, functions, modules, or
  actions with clear responsibilities.
- Prefer declarative markup, derived values, and pure data transformations over
  deeply nested control flow, scattered DOM mutation, or repeated plumbing.
- Use domain-specific names and explicit intermediate values that expose data,
  state, and interaction dependencies.
- Keep imports, formatting, and file organization consistent across the project.
  Run a compatible formatter after substantive edits whenever the environment
  provides one.

Use the formatter and configuration declared by the selected view project.
Review its diff before building. When the project declares no formatter,
preserve its existing formatting conventions and let the Studio build validate
the source.

### Add files when the starter needs more structure

A Vanilla view can keep its HTML entry document self-contained or reference
project-local CSS and JavaScript directly. Reference `.css` through
`<link rel="stylesheet">` and `.js` or `.mjs` JavaScript through
`<script src>`:

```html
<link rel="stylesheet" href="./styles/app.css" />
<script type="module" src="./scripts/app.mjs"></script>
```

The Vanilla provider resolves each path relative to the entry HTML.
`view.inspect()` exposes each exact referenced file as one of the provider's
editable source documents and adds it to the build inputs. The build copies
those files to the same paths in the browser artifact.

Leave `<base href>` out
of the entry document so those paths retain the same browser base. HTTP and
HTTPS dependency URLs need `//` and a host. Keep direct sources as leaf files by
bundling or inlining local CSS `url()` and `@import` dependencies and local
JavaScript imports or re-exports. Inspection reports the dependency's source
location when a direct file can fetch an undeclared local path and fails closed
when the pinned JavaScript grammar cannot establish that boundary.

Choose a
provider that builds the required source tree when a view needs a local asset
graph, JavaScript import graph, import map, source-phase import, component
compilation, or other project files.

Tree-sitter JavaScript 0.25 rejects a regex statement immediately after a
`break` or `continue` terminated through automatic semicolon insertion. Add an
explicit `;` after the restricted statement when another statement follows on
the next line. The same grammar rejects import attributes on re-export
statements. Preserve a default re-export by importing the remote module with its
attributes, then write `export { value as default }`. Enumerate named exports or
choose a graph-building provider for a wildcard re-export.

React and Svelte view projects can grow beyond the starter files. Put focused
components, hooks, actions, utilities, and styles beneath `src/`, then import
them from the existing application source. Provider inspection discovers
supported text files beneath `src/` recursively. The next inspection exposes
each discovered file as a source document, and the provider's existing build
input scope includes it. Create UTF-8 text with a provider-supported extension
and keep the path inside the view project.

`view.toml` stores the provider and provider options. Provider inspection owns
source discovery. A new component or utility needs an import from the
application, while the manifest remains unchanged. Unknown manifest fields are
rejected.

`view.write()` and `marimo-studio view write` conditionally replace documents
already returned by `view.inspect()`. For CLI edits, read with `--json` and pass
its `revision`, `catalog_generation`, and `view_generation` through the required
write flags. Locate the exact project root before creating another
provider-supported file:

```python
inspection = await view.inspect()
print(inspection.root)
```

Create the path with a create-if-absent filesystem operation. Studio's
guarded document writes become available after `view.inspect()` returns the
new file. For a React view, a clean factoring pass might create
`inspection.root / "src/lib/format-value.ts"`, import it from `src/App.tsx`, and
then inspect the project again:

```python
inspection = await view.inspect()
created = next(
    document
    for document in inspection.documents
    if document.path.as_posix() == "src/lib/format-value.ts"
)
assert created.access == "edit"
```

Confirm that inspection includes the new file in the intended source or build
inputs. Continue editing through filesystem tools or `view.read()` and guarded
`view.write()`, then build and validate the view.

Edit `view.toml` only when an option supported by the selected provider
genuinely changes. For example, after moving a Vanilla view's HTML entry
document to `pages/index.html`, parse and serialize TOML, preserve the selected
provider, and save through the same revision-aware API:

```python
import tomlkit

manifest = await view.read("view.toml")
config = tomlkit.parse(manifest.content)
options = config.get("options")
if options is None:
    options = tomlkit.table()
    config["options"] = options
options["entrypoint"] = "pages/index.html"

await view.write(
    "view.toml",
    tomlkit.dumps(config),
    expected_revision=manifest.revision,
)
```

### Save against the version you read

Read each affected file immediately before writing it. For a Vanilla view:

```python
document = await view.read("index.html")
updated = document.content.replace("Current heading", "Quarterly revenue")

await view.write(
    "index.html",
    updated,
    expected_revision=document.revision,
)
```

`SourceConflictError` means a person or another agent saved first. Read the file
again, incorporate both changes, and save against the current revision.

### Coordinate filesystem edits and recover

`view.inspect()` reads current disk content. Build and validation also inspect
current source. After external edits, inspect again and read the diagnostics,
`files_complete`, `project_revision`, `published_project_revision`, and
`latest_build`. `build` is the retained successful artifact. Use browser
validation to verify the presentation in a particular tab.

Compare complete inventories with `after.changes_since(before)` for added,
modified, and deleted source and build-input paths. Incomplete provider or
manifest discovery requires repair and a fresh inspection before comparison.
`view.toml` remains readable and writable through its manifest path.

For edits that pass through valid intermediate states, hold publication before
writing:

```python
hold = await view.hold_publication(owner="source-refactor", ttl=300)
print(hold.token, hold.expires_at)
```

Retain the token across calls, edit files normally, inspect, then call
`view.release_publication(token)` and build. The hold applies across processes
and expires after the requested seconds, up to 3600. Release or expiry lets the
live editor resume publication. A hold delays replacement artifacts while
source editing remains available. It does not make multi-file writes atomic.

Retain the `ViewDocument` from `view.read()` when an edit needs a source
checkpoint. To restore, read and review current content, then write checkpoint
content with `expected_revision=current.revision`. Preserve both versions when
a save conflicts. Keep durable checkpoint copies outside project build inputs.
A retained artifact keeps Preview available while failed source is repaired.
Recover an external overwrite from a retained source copy or version control.

### Place notebook results in the view

Choose the projection from the notebook evidence:

| Notebook result                                                     | View source                                     |
| ------------------------------------------------------------------- | ----------------------------------------------- |
| Complete displayed cell, including controls, logs, and errors       | `<marimo-cell name="summary"></marimo-cell>`    |
| One Python object rendered by Marimo                                | `<marimo-output value="chart"></marimo-output>` |
| JSON-compatible data or an eager dataframe consumed by browser code | Any element with `mo-value="metrics"`           |

Read the selected cell's `name`, `definitions`, and `has_output_expression`
before writing a projection. When `has_output_expression` is false, inspect its
runtime output before using `<marimo-cell>`. Use `<marimo-output>` when the cell
defines the intended object but does not display it.

Use a complete cell when the notebook already presents the result:

```html
<marimo-cell name="summary"></marimo-cell>
```

Use one rendered Python object when the view needs a specific result:

```html
<marimo-output value="chart"></marimo-output>
```

Use a value projection when browser code will adapt it for this view:

```html
<strong mo-value="metrics.total"></strong>
```

`mo-value` exposes the current value as `host.marimoValue` and publishes later
values through `marimo-value-updated`. JSON-compatible Python values become
their corresponding browser values. An eager dataframe that the active Python
environment can write as Arrow IPC becomes a shared
[Flechette `Table`](https://github.com/uwdata/flechette). Treat the table as
immutable. Its primary API is `numRows`, `numCols`, `names`, `schema`,
`get(index)`, `getChild(name)`, `select(names)`, and `toColumns()`. Call
`toArray()` when a consumer requires row objects.

React and Svelte starter helpers export `getMarimoDataSource(table)`. It returns
the table's codec, fingerprint, and shared Arrow IPC bytes under
`MARIMO_DATA_SOURCE = Symbol.for("marimo-studio.data-source")`. Treat those
bytes as immutable, or copy them before mutating them.

React starters export `MarimoTable` with `useMarimoValue`. Svelte starters
export the same table contract with `observeMarimoValue`. Keep the explicit
`mo-value` host in authored source so provider inspection can authorize the
selector.

Materialize lazy or remote dataframe queries in the notebook before projecting
them. Pandas may require PyArrow. WebAssembly notebooks need browser-compatible
dataframe and Arrow writer packages, and the encoded value must fit Studio's
value byte limit.

When inspection returns a non-empty cell `name`, use that exact name directly in
`<marimo-cell name="...">`. The native name is already a stable projection
target and needs no binding or alias. Call `workspace.bind()` only when the
complete cell is anonymous and needs a stable view-facing name.

The alias returned by `workspace.bind()` becomes an accepted value for
`<marimo-cell name="...">`. `alias` and `target` are not authored projection
attributes. Literal `name`, `value`, and `mo-value` selectors need no wildcard.
Add `data-marimo-allow="*"` when runtime code intentionally selects a target
that the provider cannot enumerate from source.

Reconsider the projection kind before changing notebook code to make a
projection host render. Presentation requirements stay in the view when the
notebook already defines the intended value.

### Mount Lens in a Studio view

[Marimo Lens](https://marimo-team.github.io/marimo-lens/) lets a person mark a
rendered result or authored page region and give that exact surface to a
code-mode agent. When enabling Lens, addressing selections, or needing metadata
details beyond the traceability conventions, import `marimo_lens.agent` and run
`help(marimo_lens.agent)` in the notebook environment. Follow its packaged skill
and browse the [target metadata reference](https://marimo-team.github.io/marimo-lens/concepts/targets)
as needed. Reuse that discovery for the same environment and Lens version,
combining it with an already-needed inspection call when possible. Routine view
authoring follows the conventions directly, without Lens setup prompts or
additional discovery calls.

To enable feedback, install `marimo-studio[lens]` (or `marimo-lens>=0.1.2`) in
the notebook environment. Development previews reuse the notebook's Lens or mount
one when installed. Reuse that instance without adding a Lens cell or projection.
For an explicitly authored Lens in another Server view, define one value:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
None
```

The final `None` keeps the Lens dock on the projected Studio surface. Rendering
`studio_lens` as the notebook cell output also mounts a notebook dock.

Project the value once in each view that should collect feedback. Link custom
rendered regions to their existing notebook input hosts:

```html
<marimo-output value="studio_lens"></marimo-output>

<span id="revenue-data" hidden mo-value="quarterly_revenue"></span>
<section
  data-marimo-lens-inputs="revenue-data"
  data-marimo-lens-label="Quarterly revenue"
  data-marimo-lens-render-source='{"path":"index.html"}'
  data-marimo-lens-context
>
  <!-- Render the custom revenue chart here. -->
</section>
```

`STUDIO_RESULT_SELECTOR` covers connected `marimo-cell`, `marimo-output`, and
`mo-value` hosts, parents containing hidden value hosts, and regions annotated
with `data-marimo-lens-inputs`. Studio also scopes default HTML picking to
`#app-shell`. Ordinary HTML is selectable without annotation. Lens frames the
nearest semantic region or block and retains the clicked child's bounded DOM
hint. Set `data-marimo-lens-scope=".card, header, figure"` on the shell to customize
grouping for that view. Mark a parent that should outrank smaller nested targets with
`data-marimo-lens-target` and a stable, unique ID. Each view owns these regions
in its authored markup. Keep labels and rendering-source references on the
selected root. Such selections have empty notebook provenance.

Use the packaged Marimo Lens skill for the feedback lifecycle. Pass the
captured `SelectionReference` to Lens activity and reveal calls. Use its
`cells` as notebook provenance and `target["sources"]` for exact value selectors.
For a DOM target, use `documentPath`,
`domSelector`, and the active Studio view to locate the owning source document,
then build, show, and validate that view before resolving the selection.

## Build, show, and verify

Build after editing view source:

```python
build = await view.build()
print(build.revision)
```

A failed build leaves the last successful view available. Repair the reported
source issue and build again. Call `view.inspect()` after a failure and read the
diagnostic `message`, `hint`, and source location before editing.

Show the view in the next code-mode execution:

```python
import marimo_studio.agent as studio_agent

await studio_agent.current_workspace().view("dashboard").show()
```

Use the environment's browser tool to exercise the affected controls,
navigation, conditional content, and dynamic results in the same Studio tab.

Validate in another code-mode execution after the view settles:

```python
import marimo_studio.agent as studio_agent

report = await studio_agent.current_workspace().view("dashboard").validate(level="browser")
for issue in report.issues:
    print(issue.severity, issue.message, issue.advice)
```

Repeat edit, build, show, interaction, and validation until `report.ok` is true.
Inspect visible changes at wide and narrow widths.

Browser validation proves that the current presentation revision and projection
hosts reached their expected lifecycle states. It does not prove spacing,
sizing, responsive layout, scroll choreography, or visual polish. Capture and
inspect the rendered browser page for visual work. Report the visual check as
blocked when the environment cannot capture or inspect it.

## Review list before handoff

Complete this review before handing off a view:

- Check every displayed analytical value and claim against its notebook
  producer. Replace literal copies in HTML, JSX, Svelte, JavaScript, and other
  view source with live projections. NEVER hand off hardcoded results that
  could use `mo-value`, `marimo-output`, or `marimo-cell`.
- Change a relevant notebook input or control and verify that projected values
  and custom renderers update, including analytical prose.
- Verify Lens metadata on custom regions: labels, complete input links, current
  render-source paths, and image context where appropriate. Keep annotations
  outside native output subtrees and verify selection provenance when Lens is
  available.
- Check the view against the chosen design source and record durable design
  decisions in the project's `AGENTS.md`.
- Build, show, and pass browser validation for the final revision. Inspect it
  at wide and narrow widths and exercise the affected controls and navigation.

## Run or export

Choose the runtime from the visitor's task:

| Runtime                    | Result                                                                     |
| -------------------------- | -------------------------------------------------------------------------- |
| Server, `server`           | Live notebook execution with the server's packages, files, and credentials |
| WASM, `wasm`               | New notebook states computed in the visitor's Pyodide worker               |
| Zero-Python, `zero-python` | Finite precomputed states with notebook source retained on the producer    |

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
An omitted state file prepares the initial notebook state. Use
explicit state rows when valid combinations are sparse. Keep browser-only
filtering of projected data in the view. A matrix prepares every combination
of its input choices.

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

## Report completion

Report the notebook, view, changed source files, artifact revision, and the
static, runtime, and browser validation performed. Leave the notebook and view
runnable.
