# Lens in Studio views

[Marimo Lens](https://marimo-team.github.io/marimo-lens/) lets a person mark a
rendered result or authored page region and give that exact surface to a
code-mode agent. When enabling Lens, addressing selections, or needing metadata
details beyond the traceability conventions, import `marimo_lens.agent` and run
`help(marimo_lens.agent)` in the notebook environment. Follow its
packaged skill and browse the [target metadata reference](https://marimo-team.github.io/marimo-lens/custom-targets)
as needed. Reuse that discovery for the same environment and Lens version,
combining it with an already-needed inspection call when possible. Routine view
authoring follows the conventions directly, without Lens setup prompts or
additional discovery calls.

To enable feedback, install `marimo-studio[lens]` in the notebook environment
and restart a running notebook. When the notebook imports no Lens, Marimo mounts
one and the development preview reuses it, so selections from the Notebook pane
dock and the preview dock reach you together. Use that instance without adding a
Lens cell or projection. For an explicitly authored Lens in another Python-runtime view,
define one value:

```python
from marimo_lens import Lens
from marimo_studio import STUDIO_RESULT_SELECTOR

studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)
None
```

The final `None` keeps the Lens dock on the projected Studio surface. Rendering
`studio_lens` as the notebook cell output also mounts a notebook dock. Studio
skips Marimo's automatic Lens in a notebook that imports Lens, so `studio_lens`
is the notebook's only Lens.

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
grouping for that view. Use `data-marimo-lens-target` and a stable, unique ID
for a declared authored region. Each view owns these regions in its markup.
Keep labels and rendering-source references on the selected root. Plain HTML
regions without notebook input hosts have empty notebook provenance.

Use the packaged Marimo Lens skill for the feedback lifecycle. Pass the
captured `SelectionReference` to Lens activity and reveal calls. Use its
`cells` as notebook provenance and `target["sources"]` for exact value selectors.
For a DOM target, use `documentPath`,
`domSelector`, and the active Studio view to locate the owning source document,
then build, show, and validate that view before resolving the selection.
