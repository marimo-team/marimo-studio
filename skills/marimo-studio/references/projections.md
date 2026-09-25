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

## Select targets

The alias returned by `workspace.bind()` becomes an accepted value for
`<marimo-cell name="...">`. `alias` and `target` are not authored projection
attributes. Literal `name`, `value`, and `mo-value` selectors need no wildcard.
Add `data-marimo-allow="*"` when runtime code intentionally selects a target
that the provider cannot enumerate from source.

Reconsider the projection kind before changing notebook code to make a
projection host render. Presentation requirements stay in the view when the
notebook already defines the intended value.

## Connect custom results to their producers

Apply these conventions while authoring every view, even when Lens is not
installed, so adding Lens exposes named targets and their source context.
Keep metadata on authored regions and projection hosts, outside native Marimo
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
