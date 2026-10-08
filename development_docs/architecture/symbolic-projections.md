# Symbolic projections

Projection hosts name notebook results. Studio resolves those names to semantic
producers and validates the live dependency closure before runtime dispatch.

See the [canonical ownership map](../architecture.md#ownership) for package
responsibilities.

## Source declarations

Three host forms share one lifecycle:

```html
<marimo-cell name="summary"></marimo-cell>
<marimo-output value="chart"></marimo-output>
<strong mo-value="metrics.total"></strong>
```

Provider inspection reports a `ProjectionSite` for each declaration with its
source path, line, column, kind, targets, and the byte offset inside its start
tag. Core derives the trusted site ID and inserts it at that offset
in the disposable build snapshot, not authored source.

A rendered document declares `RenderValue`, `RenderOutput`, and `RenderCell`
records in place of sites. Core turns each distinct value target into one value
site on a hidden `mo-value` host in the generated viewer page, each output
target into one output artifact site with the read's accept list and a hidden
`marimo-output` host, and each cell target into one cell artifact site with its
accept list and a hidden `marimo-cell` host. Render reads travel the ordinary
projection paths and authorization, and the hosts' update events trigger the
next render. Read sites use their own ID namespace, so a page host and a read
of one target never share an ID.

Accept lists belong to output targets. Inspection gives every literal read of a
target the same list and rejects one on a `"*"` site, so resolution, kernel
authorization records, the Pyodide bridge, and the Prepared compiler look up a
target's list from its literal sites. Page sites accept images marimo's
renderer shows. Hosts render nothing for other media, such as the PDF a hidden
document host carries for the renderer.

An output with an accept list renders through marimo-export's
`values.represent()` in every runtime: the kernel output renderer, the Pyodide
bridge, and Prepared exports through the `media` exporter. The bridge loads
the source of that standard-library module and of Studio's
`_projections/media_output.py` into its hidden cell, because Pyodide has
neither package installed. `media_output()` carries a representation as marimo
output data: a base64 data URL, wrapped in a marimo mimebundle with the display
size of a PNG rendered at `MEDIA_SCALE`, as marimo sends its own high-density
figures. The zero-python loader builds the same data from the `media`
exporter's `BlobAsset` metadata, and `output_representation()` decodes posted
outputs. Value targets, output targets, and kernel authorization records parse
through marimo-export's `ValueSelector`, which owns the selector grammar and
its limits.

Every provider can declare literal targets. A provider analyzer may also
authorize a finite target set or explicit wildcard access. An analyzer that
cannot bound an expression rejects it unless that provider supports a wildcard
declaration:

```tsx
<marimo-cell name={runtimeTarget} data-marimo-allow="*" />
```

Analyzer uncertainty never silently grants wildcard access.

## Notebook symbols

`NotebookSymbolGraph` contains:

- semantic cell IDs and source spans
- native cell names
- configured aliases
- variable producers
- upstream and downstream relationships

Resolution produces a target, semantic producer, optional selector, and
dependency closure. Cell sites select a named cell. Output and value sites
select a variable root plus optional attribute or item steps.

## Presentation authorization

The published artifact supplies trusted artifact sites. The browser
supplies mounted instance ID and target. The server joins them with the current
presentation and notebook symbols.

Authorization checks:

1. The artifact and presentation are current.
2. The site exists and owns the projection kind.
3. The site's targets include the target.
4. The target resolves to one notebook producer.
5. The live kernel capability covers the current dependency closure.

Kernel capabilities use an [HMAC](https://www.rfc-editor.org/rfc/rfc2104), a
keyed message digest, to bind notebook, session, target, producer, selector,
and closure. Browser requests cannot widen them.

## Runtime projections

`ProjectionInventory` resolves an ordered batch of authored hosts against one
projection revision. Each host retains site ID, instance ID, target,
phase, and runtime cell ID. Type-specific adapters own complete cells, rendered
outputs, and browser values. Value descriptors carry JSON-compatible values directly or
[Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc)
with a [Flechette](https://github.com/uwdata/flechette) data-source owner. Arrow
IPC is the columnar transfer format. Flechette owns the decoded browser table.

DOM mutation processing batches additions and removals. Moving an existing host
preserves the instance and its resource owners. Retargeting preserves the DOM
instance ID, releases resource ownership for the prior target, and acquires the
selected runtime result for the new target. Final removal releases the remaining
owners.

## Server and browser worker parity

Server and WebAssembly runtimes consume the same symbolic target and selector
grammar. Conformance cases compare producer and dependency closure for each
environment.

The browser worker receives the notebook data it needs for local resolution.
The server runtime resolves against the saved notebook and revalidates the live
kernel graph.

## Rendered evidence

Projection hosts expose their lifecycle through DOM attributes and events.
Server-side analysis derives source locations, symbolic producers, selectors,
closures, and policy diagnostics. Browser tools inspect the actual hosts and
assert the application's rendered results.

The document exposes Studio readiness and its committed presentation revision.
A dynamic projection's lifecycle belongs to its current DOM instance and target.
Retargeting and removal release the previous instance's runtime ownership.

## Failure behavior

- Missing literal targets are static diagnostics.
- Unbounded expressions without explicit wildcard access are source diagnostics.
- Disabled or errored producers are runtime diagnostics.
- A removed host releases its final runtime owner.

Protect literal, finite-set, explicit-wildcard, retarget, move, removal,
server-worker parity, and kernel capability cases.
