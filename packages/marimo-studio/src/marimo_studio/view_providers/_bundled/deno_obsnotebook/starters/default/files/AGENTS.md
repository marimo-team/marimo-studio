# Observable Notebook Kit view

Follow the Marimo Studio skill for notebook ownership, projections, and
verification. This file owns Notebook Kit presentation and dataflow conventions.

Edit `src/index.html` using Notebook Kit's `<notebook>` and `<script>` cell
format. Studio builds it with the project's locked Deno and Vite dependencies.
`src/page.tmpl` supplies the page shell and `src/style.css` supplies styling.
Keep the template's `<main id="app-shell">` around the notebook output.

Put Studio projection hosts in `type="text/html"` cells or the page template:

```html
<script id="3" type="text/html">
    <marimo-cell name="controls"></marimo-cell>
    <marimo-output value="summary"></marimo-output>
</script>
```

To use live notebook data in Observable expressions, give an HTML cell an
`output` name and pass its host to the supplied generator:

```html
<script id="4" type="text/html" output="totalHost">
    <span hidden mo-value="total"></span>
</script>
<script id="5" type="module">
import { marimoValue } from "./lib/marimo-value.js";
const total = marimoValue(totalHost);
</script>
<script id="6" type="text/html">
    <p>Total: ${total}</p>
</script>
```

The generator reads the current value, subscribes to updates, and releases its
listeners when Observable invalidates it. It also carries Arrow table values. A
terminal projection error stops the generator and appears in dependent cells.
Reload the view after correcting the error. Keep the value host independent of
cells that consume its value.

Use literal targets or conditional expressions with literal branches for
Prepared exports. Unbounded interpolated selectors require
`data-marimo-allow="*"` and the Server or WebAssembly runtime. Observable can
recreate these hosts as its inputs change. Put projections in HTML cells rather
than constructing them in JavaScript strings or Markdown. Studio authorizes each
authored host and owns its native output subtree.

Configure native control combinations in `states.yaml` for Prepared exports. An
omitted state file captures the initial notebook state.

Keep shared computation, data loading, controls, and domain decisions in the
Marimo notebook. Use Observable cells for this view's presentation and local
interaction. Build-time interpreter cells and database queries are rejected.
Relative `FileAttachment` assets under `src/` are included in builds. Bare npm
imports are bundled by Vite. Notebook Kit's `npm:` and `jsr:` imports use remote
browser modules, so use bare imports for views that must work offline.

Use the Deno supplied by `marimo-studio[deno]` in the notebook's Python
environment. Pin added npm dependencies in `package.json`, then regenerate
`deno.lock` with
`uv run -- deno install --frozen=false --node-modules-dir=auto --no-save`.
Source exposes the lockfile as read-only. Keep authored inputs in `src/` and
public assets in `public/`. Build failure retains the last published preview.

## Link custom results to notebook inputs

Keep named HTML value hosts independent of the Observable cells consuming them.
Link custom results to every host they consume, and give each region a readable
label and rendering-source reference to `src/index.html` or its owning module.
Follow the installed Studio skill's `references/projections.md` for the shared
contract:

```python
import marimo_studio

print(marimo_studio.agent.skill().file("references/projections.md").read_text())
```

## Maintain project ignore rules

You own this view project's `.gitignore`. When adding libraries, extensions, or
build tools, ignore their generated files, caches, local configuration, and
secrets. Keep authored source, dependency manifests, and lockfiles tracked.
Studio supplies workspace rules for its own artifacts and locks. Check
`git status --short --ignored` after running new tooling and update the view's
ignore rules before committing.
