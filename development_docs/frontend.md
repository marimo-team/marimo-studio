# Frontend

The browser runtime mounts Marimo outputs into authored view documents. Source
lives in `frontend/`. `make build` writes package assets to
`src/marimo_studio/_static/server-runtime/`.

## Source layout

| Path | Responsibility |
| --- | --- |
| `frontend/src/cell-host.ts` | `<marimo-cell>` lifecycle and measured loading space |
| `frontend/src/cell-bindings.ts` | Live cell lookup by Marimo name or editor ID |
| `frontend/src/value-bindings.ts` | `mo-value` reads, caching, and retry |
| `frontend/src/readiness.ts` | Page readiness state and browser API |
| `frontend/src/runtime-config.ts` | Active view runtime configuration |
| `frontend/src/dev-reload.ts` | Stylesheet refresh, shell swap, and view switch |
| `frontend/src/studio.ts` | Studio layout, view selector, and preview lifecycle |
| `frontend/src/marimo-adapter/` | Private Marimo imports and output portals |
| `frontend/tests/` | Runtime state and protocol tests |

## Runtime flow

`#marimo-runtime-root` remains mounted for the document lifetime. Cell and
value hosts project current store state into `#app-shell`.

Runtime configuration maps each template alias to a native cell name or an
active session ID. The browser resolves that target against Marimo's current
cell store. The first run-mode configuration uses IDs from the disk graph while
Marimo creates the browser session. Later refreshes include the browser's
session ID, and Studio reconciles anonymous aliases against that session's
document. Notebook insertions, moves, and serialization can change IDs in a
fresh disk parse while an active session keeps its live IDs stable.

HTMX observes the visible document. A development refresh parses the selected
view document and swaps its shell through HTMX. Generated cell-host IDs
preserve matching output DOM. New hosts attach to the current runtime store.

View switching commits the support URL, runtime configuration, title, styles,
and shell as one transition. A notebook save refreshes cell bindings in place.
If an HTML save reaches Studio before the corresponding notebook autosave, the
next notebook or target-view save retries that view's pending shell.
Each development event stream reconciles the shell after establishing its file
baseline, including after a reconnect.

## Build

```console
make install
make build
```

Set `MARIMO_REPO` to build against a local Marimo checkout whose version
matches `uv.lock`:

```console
MARIMO_REPO=/path/to/marimo make build
```

The build checks out the Marimo version resolved in `uv.lock` and writes that
version to `build-meta.json`.

After a Marimo upgrade:

```console
make check
make package
```

Exercise named view switching, cell outputs, controls, anywidgets, value
selectors, HTMX swaps, and a base-path deployment in a real browser.
