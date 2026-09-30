# Projections and custom rendering

Read when consuming dataframe values, adding custom renderers, or choosing
dynamic projection targets. Use the selected project's adapters and types.

## Consume live values

`mo-value` exposes the current value as `host.marimoValue` and publishes later
values through `marimo-value-updated`. JSON-compatible Python values become
their corresponding browser values. An eager dataframe that the active Python
environment can write as Arrow IPC becomes a shared
[Flechette `Table`](https://github.com/uwdata/flechette). Treat the table as
immutable. Its primary API is `numRows`, `numCols`, `names`, `schema`,
`get(index)`, `getChild(name)`, `select(names)`, and `toColumns()`. Call
`toArray()` when a consumer requires row objects. Integer columns, including
64-bit integers, read as numbers, list cells as arrays, and dates and
timestamps as epoch milliseconds. Reading a 64-bit value beyond
`Number.MAX_SAFE_INTEGER` throws.

React and Svelte starter helpers export `getMarimoDataSource(table)`. It returns
the table's codec, fingerprint, and shared Arrow IPC bytes under
`MARIMO_DATA_SOURCE = Symbol.for("marimo-studio.data-source")`. Treat those
bytes as immutable, or copy them before mutating them.

React starters export `MarimoTable` with `useMarimoValue`. Svelte starters
export the same table contract with `observeMarimoValue`. The React hook's
`error` and the Svelte and HTML helpers' `onError` receive the host's
`{ selector, code, message, hint }` error. Keep the explicit `mo-value` host in
authored source so provider inspection can authorize the selector.

Materialize lazy or remote dataframe queries in the notebook before projecting
them. Pandas may require PyArrow. WebAssembly notebooks need browser-compatible
dataframe and Arrow writer packages. Each projected value must encode within
1,000,000 bytes in every runtime. Filter, aggregate, or split larger tables into
separate notebook values, then select one at runtime as described in
[Select targets](#select-targets).

## Select targets

The alias returned by `workspace.bind()` becomes an accepted value for
`<marimo-cell name="...">`. `alias` and `target` are not authored projection
attributes. Literal `name`, `value`, and `mo-value` selectors need no wildcard.
Add `data-marimo-allow="*"` when runtime code intentionally selects a target
that the provider cannot enumerate from source.

When a table exceeds the 1,000,000-byte value limit, publish a compact index
table plus a dictionary of per-item frames with string keys, such as
`details = {str(key): frame for key, frame in groups}` and
`default_details = details[default_key]`. Start the host on `default_details`,
then change its selector to a key read from a row of the index table:

```html
<span id="details" hidden mo-value="default_details" data-marimo-allow="*"></span>
```

```js
const select = (key) =>
  document.getElementById("details").setAttribute("mo-value", `details[${JSON.stringify(key)}]`);
```

Keep the key as a column in each frame so the view can match arriving rows to
the current selection. A wildcard host resolves its target while the notebook
runs, so serve it with the Python runtime or export it with `--runtime wasm`.
For a Prepared export, author one host per item.

Views change notebook state through native marimo controls. Project a
control's cell with `<marimo-cell>`, and keep other selection state in the
browser.

Reconsider the projection kind before changing notebook code to make a
projection host render. Presentation requirements stay in the view when the
notebook already defines the intended value.

## Connect custom results to their producers

Apply these conventions while authoring every view, even when Lens is not
installed, so adding Lens exposes named targets and their source context.
Keep metadata on authored regions and projection hosts, outside native marimo
output subtrees.

Custom JavaScript rendering must consume live projections, handle their
updates, and declare every kernel input:

- Place hidden `mo-value` hosts directly inside the result, or use
  `data-marimo-lens-inputs="rows-data summary-data"` to reference projection hosts by
  unique, stable HTML IDs in the same document. Include every input, including
  shared inputs used through JS transforms. References must point directly to
  mounted `mo-value`, `marimo-output`, or `marimo-cell` hosts. Missing or duplicate
  IDs make the result unavailable to Lens. Never fabricate runtime metadata.
- Annotate individual metrics, rows, charts, and report pages. Prefer narrow
  selectors such as `summary.events`. Bind dynamic selectors and source IDs to
  the state that renders the result. Use `data-marimo-allow="*"` for selectors
  the provider cannot bound at build time. Unbounded selectors require Server
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
