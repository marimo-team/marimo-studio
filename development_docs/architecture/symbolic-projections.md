# Symbolic projections

Frontend mounts name notebook results. Studio resolves those names to semantic
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

Provider inspection records the source path, line, column, kind, and allowed
targets for each declaration. Build instrumentation adds the trusted mount ID
to the disposable snapshot, not authored source.

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
dependency closure. Cell mounts select a named cell. Output and value mounts
select a variable root plus optional attribute or item steps.

## Presentation authorization

The published artifact supplies trusted source declarations. The browser
supplies mounted instance ID and target. The server joins them with the current
presentation and notebook symbols.

Authorization checks:

1. The artifact and presentation are current.
2. The declaration exists and owns the projection kind.
3. The target is allowed by the declaration.
4. The target resolves to one notebook producer.
5. The live kernel capability covers the current dependency closure.

Kernel capabilities are HMAC-bound to notebook, session, target, producer,
selector, and closure. Browser requests cannot widen them.

## Runtime mounts

One host store tracks declaration ID, instance ID, target, phase, and runtime
cell ID. Small type-specific adapters own complete cells, rendered outputs, and
JSON values.

DOM mutation processing batches additions and removals. Moving an existing host
does not release its owner. Retargeting keeps the instance owner while replacing
its selected runtime result. Final removal releases the owner.

## Server and browser worker parity

Server and WebAssembly runtimes consume the same symbolic target and selector
grammar. Conformance cases compare producer and dependency closure for each
environment.

The browser worker receives the notebook data it needs for local resolution.
The server runtime resolves against the saved notebook and revalidates the live
kernel graph.

## Evidence

Browser observations report mount ID, instance ID, target, phase, runtime cell,
and error. Server-side analysis derives source locations, symbolic producers,
selectors, closures, and policy diagnostics.

Evidence is accepted only for the pending request ID and its browser client,
binding and runtime sessions, active-view generation, view, runtime, runtime
instance, and presentation revision. Observation sequences must increase. The
record also captures the public query and projection-instance evidence, and a
ready observation requires every projected instance to be ready. A view,
binding, runtime, or source revision change invalidates pending focused
evidence.

## Failure behavior

- Missing literal targets are static diagnostics.
- Unbounded expressions without explicit wildcard access are source diagnostics.
- Disabled or errored producers are runtime diagnostics.
- Stale browser evidence is rejected.
- A removed host releases its final runtime owner.

Protect literal, finite-set, explicit-wildcard, retarget, move, removal,
server-worker parity, and kernel capability cases.
