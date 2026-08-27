---
title: Notebook result mounts
description: Resolve complete cells, rendered Python objects, and values from frontend source.
---

# Notebook result mounts

Studio recognizes three frontend declarations:

| Kind   | Source form                       | Result                            |
| ------ | --------------------------------- | --------------------------------- |
| Cell   | `<marimo-cell name="summary">`    | Complete Marimo cell output       |
| Output | `<marimo-output value="chart">`   | One Marimo-rendered Python object |
| Value  | `<span mo-value="metrics.total">` | JSON-compatible value             |

Declarations belong inside the view's `#app-shell`.

## Target grammar

A cell target is a native Marimo cell name or configured alias.

Output and value targets start with a notebook variable and may select nested
attributes or items:

```text
metrics.total
results["overview"]
rows[0].label
```

Python expressions, calls, operators, slices, and private attributes are not
target syntax.

## Static authorization

The view build records each source declaration. Literal targets authorize one
name and work with every provider. A provider analyzer may authorize finite
dynamic target sets or explicit wildcard access. Each accepted target still
resolves through the current notebook graph and runtime capability policy.

## Resolution

Studio maps each target to its notebook producer. Resolution fails when a
target is missing, ambiguous, malformed, or outside the declaration's allowed
set. Complete-cell mounts resolve a named cell. Output and value mounts resolve
the variable root and selector steps.

## Runtime authorization

The built declaration supplies the result kind. A browser mount supplies its
declaration ID, instance ID, and target. Server requests also carry a
short-lived capability bound to the notebook, session, and resolved target.

The kernel revalidates the live closure before dispatch. A browser cannot widen
an artifact declaration or reuse a capability for another target.

## Lifecycle

Retargeting an existing host keeps its instance owner and replaces the selected
runtime result. Moving a host within the document keeps the owner. Final removal
releases projected controls, outputs, virtual files, and widgets after their
last consumer leaves.

Value mounts may share a target and receive the same runtime read. A cell or
rendered-output target has one mounted owner. Additional cell or output hosts
report a duplicate-host diagnostic.

## Limits

| Boundary                    | Limit |
| --------------------------- | ----: |
| Active projection instances |   512 |
| Unique cell targets         |   256 |
| Unique output targets       |   100 |
| Unique value targets        |   100 |
| Instance ID bytes           |   256 |
| Target bytes                | 4,096 |
| Value selector path steps   |    64 |

The browser rejects the first host or target beyond a limit and reports a
projection diagnostic at that host.

## Diagnostics

Static diagnostics include:

- missing or duplicate target attributes
- invalid target syntax
- dynamic targets outside the selected provider's analyzer capability
- missing or ambiguous notebook producers
- source declarations outside `#app-shell`

Runtime diagnostics include disabled or errored producers, missing selector
steps, output formatting failures, oversized responses, stale presentations,
and invalid capabilities.

```console
marimo-studio validate analysis.py --view dashboard --level static
marimo-studio validate analysis.py --view dashboard --level runtime
```

[Notebook results](../guide/notebook-results.md) develops the authoring
workflow. [Runtime behavior](runtimes.md) defines Server and WebAssembly
execution.
