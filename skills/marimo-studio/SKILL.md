---
name: marimo-studio
description: >-
  Turn a Marimo notebook into focused web pages. Use when an agent needs to
  inspect notebook and page source, edit a page safely, build it, show it in
  Studio, validate the rendered result, run it, or export it.
---

# Author Marimo Studio pages

The notebook computes. The page presents. Studio connects them.

Keep data access, transformations, controls, and reusable results in notebook
cells. Keep page structure, wording, styles, and browser interaction in page
source.

Studio calls each named page a view.

## Work with the current Studio tab

Open the current notebook workspace once in each code-mode execution:

```python
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = workspace.view("dashboard")
```

Use `workspace.status()` to inspect configured views before creating one. Use
`workspace.view(name)` for an existing page. Create a page only when the
requested name is absent:

```python
status = await workspace.status()
if not any(item.name == "dashboard" for item in status.views):
    view = await workspace.create_view("dashboard")
```

The default creation path produces one editable HTML page and starter-specific
agent instructions. Inspect installed starting points only when the user asks
for a particular frontend.

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

Inspect the page to discover the files Studio exposes:

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

Aggregate valid revenue rows so the page can compare segments directly.
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

Edit only project-relative files whose access is `edit`. Use view files for page
structure, wording, styles, and browser interaction.

### Choose visual direction

Choose visual direction in this order:

1. Follow the user's explicit style direction.
2. Follow the starter project's `DESIGN.md` when it exists.
3. Otherwise use the current
   [Marimo design guide](https://raw.githubusercontent.com/marimo-team/marimo/refs/heads/main/DESIGN.md)
   as the aesthetic reference.

Read the selected design source before visual authoring. Apply its visual
character, tokens, typography, surfaces, component treatment, and motion
guidance so the selected direction shapes the whole page.

### Keep view source maintainable

Treat agent-authored page source as maintained application code. A person should
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

Use the formatter and configuration declared by the selected view project. When
that project has no formatter and Python `uv` or `uvx` is available, run npm
formatter CLIs through Deno without managing a separate Node.js installation:

```console
uvx deno x -y oxfmt .
uvx deno x -y prettier --write .
```

`uvx deno` provisions the Deno executable through Python `uv`. `deno x -y`
performs the same one-shot package-execution role as `npx -y`. Run the command
from the view project root, pass the formatter's appropriate paths and config,
review the resulting diff, and then build the view.

### Add files when the starter needs more structure

React and Svelte view projects can grow beyond the starter files. Put focused
components, hooks, actions, utilities, and styles beneath `src/`, then import
them from the existing application source. Provider inspection discovers
supported text files beneath `src/` recursively. The next inspection exposes
each discovered file as a source document, and the provider's existing build
input scope includes it. Create UTF-8 text with a provider-supported extension
and keep the path inside the view project.

The HTML starter is a self-contained `index.html`. Keep its project-owned CSS
and JavaScript inline. Create a React or Svelte view when clean factoring needs
separate local files.

`view.toml` stores the provider and provider options. Provider inspection owns
source discovery. A new component or utility needs an import from the
application, while the manifest remains unchanged. Unknown manifest fields are
rejected.

`view.write()` and `marimo-studio view write` conditionally replace documents
already returned by `view.inspect()`. They do not create an absent path. Locate
the exact project root before creating a file with the environment's file-edit
tool:

```python
status = await workspace.status()
project = next(item for item in status.views if item.name == "dashboard")
print(project.path)
```

For a React view, a clean factoring pass might create
`project.path / "src/lib/format-value.ts"`, import it from `src/App.tsx`, and
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

Continue only after inspection returns the new path. Use `view.read()` and
revision-aware `view.write()` for later edits, then build and validate the view.

Edit `view.toml` only when an option supported by the selected provider
genuinely changes. For example, after moving a Vanilla view's self-contained
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

Read each affected file immediately before writing it:

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

### Place notebook results on the page

Choose the projection from the notebook evidence:

| Notebook result                                               | Page source                                     |
| ------------------------------------------------------------- | ----------------------------------------------- |
| Complete displayed cell, including controls, logs, and errors | `<marimo-cell name="summary"></marimo-cell>`    |
| One Python object rendered by Marimo                          | `<marimo-output value="chart"></marimo-output>` |
| JSON-compatible data consumed by browser code                 | Any element with `mo-value="metrics"`           |

Read the selected cell's `name`, `definitions`, and `has_output_expression`
before writing a projection. When `has_output_expression` is false, inspect its
runtime output before using `<marimo-cell>`. Use `<marimo-output>` when the cell
defines the intended object but does not display it.

Use a complete cell when the notebook already presents the result:

```html
<marimo-cell name="summary"></marimo-cell>
```

Use one rendered Python object when the page needs a specific result:

```html
<marimo-output value="chart"></marimo-output>
```

Use a JSON-compatible value when browser code will adapt it for this page:

```html
<strong mo-value="metrics.total"></strong>
```

When inspection returns a non-empty cell `name`, use that exact name directly in
`<marimo-cell name="...">`. The native name is already a stable projection
target and needs no binding or alias. Call `workspace.bind()` only when the
complete cell is anonymous and needs a stable page-facing name.

The alias returned by `workspace.bind()` becomes an accepted value for
`<marimo-cell name="...">`. `alias` and `target` are not authored projection
attributes. Literal `name`, `value`, and `mo-value` selectors need no wildcard.
Add `data-marimo-allow="*"` when runtime code intentionally selects a target
that the provider cannot enumerate from source.

Reconsider the projection kind before changing notebook code to make a page host
render. Presentation requirements stay in the view when the notebook already
defines the intended value.

## Build, show, and verify

Build after editing page source:

```python
build = await view.build()
print(build.revision)
```

A failed build leaves the last successful page available. Repair the reported
source issue and build again. Call `view.inspect()` after a failure and read the
diagnostic `message`, `hint`, and source location before editing.

Show the page in the next code-mode execution:

```python
import marimo_studio.agent as studio_agent

await studio_agent.current_workspace().view("dashboard").show()
```

Use the environment's browser tool to exercise the affected controls,
navigation, conditional content, and dynamic results in the same Studio tab.

Validate in another code-mode execution after the page settles:

```python
import marimo_studio.agent as studio_agent

report = await studio_agent.current_workspace().view("dashboard").validate(level="browser")
for issue in report.issues:
    print(issue.severity, issue.message, issue.advice)
```

Repeat edit, build, show, interaction, and validation until `report.ok` is true.
Inspect visible changes at wide and narrow widths.

Browser validation proves that the current page revision and projection hosts
reached their expected lifecycle states. It does not prove spacing, sizing,
responsive layout, scroll choreography, or visual polish. Capture and inspect
the rendered page for visual work. Report the visual check as blocked when the
environment cannot capture or inspect it.

## Run or export

Run through marimo when the notebook needs Python packages, local files,
databases, or server credentials:

```console
uv run --with marimo-studio marimo run notebook.py --sandbox
```

Export when the notebook and its data can run in Pyodide:

```console
marimo-studio view export dashboard \
  --target notebook.py \
  --output dist/dashboard
```

The browser and static export receive the saved notebook source. Review the
notebook, public files, data URLs, and dependencies before publishing.

## Report completion

Report the notebook, view, changed source files, built page revision, and the
static, runtime, and browser validation performed. Leave the notebook and page
runnable.
