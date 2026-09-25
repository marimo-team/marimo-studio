# Reveal.js React starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the Reveal.js project supplied
by this starter.

## Project intent

Keep this section current with the audience, presentation goal, concrete project
details, visual direction, interaction priorities, and approved libraries.
Preserve decisions that should guide later agents.

- Audience: a lecturer presenting quadratic programs to a class.
- Goal: follow the notebook's argument slide by slide, from the standard form to
  the key ideas, and let the room change the problem live.
- The title slide shows the complete figure beside the title, as a preview of
  the figure the class later changes live.
- The two-dimensional example builds the figure in four fragments: walls,
  feasible region, level curves, and the solution.
- The "Interactive example" slide keeps the notebook prompt, the native controls,
  the live figure, and the solution summary together so the prompt can be tried
  on that slide.
- The figure and the dual bars draw from the notebook's `region`, `bowl`, and
  `solution` values in `src/problem.tsx` and `src/App.tsx`.
- Slides show notebook content and presentation wording only.

## Compose the deck

`src/App.tsx` owns the `Deck` and its ordered `Slide`, `Stack`, and `Fragment`
children. Keep one audience claim or decision per slide. Use React components
for repeated layouts and local interaction.

The target records mapped to `<Slide>` in `src/App.tsx` start with one record
for each enabled cell that may display output, including literal Markdown. A
Markdown heading supplies its slide label. Edit those records and their
surrounding JSX to keep, reorder, group, or replace slides as the presentation
argument develops.

Pass Reveal configuration through `Deck.config`. Register plugins through
`Deck.plugins` when the deck first mounts. Keep the plugin array stable because
Reveal initializes plugins once for each deck instance.

Keep `scrollActivationWidth: 0` in the deck configuration. Reveal's automatic
narrow scroll view reads `sessionStorage`, which is unavailable inside Studio's
isolated presentation frame. Slide mode scales to narrow frames and remains
available in Server, WebAssembly, and static delivery.

Import `reveal.js/reveal.css` for the structural styles. Keep the deck's visual
system in `src/style.css`, including typography, spacing, colors, controls, and
progress treatment. Preserve full-height sizing for `html`, `body`,
`#app-shell`, and `.reveal`.

## Place notebook results on slides

`src/marimo-studio.d.ts` types the Studio custom elements and attributes. Keep
its reference at the top of `src/App.tsx`.

Place a cell or output directly inside a `Slide` after selecting a target from
the notebook:

```tsx
<Slide>
  <h2>Regional performance</h2>
  <marimo-output value="regional_chart" />
</Slide>;
```

Use `src/lib/use-marimo-value.ts` when a React component consumes a notebook
value or eager dataframe:

```tsx
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

type Row = { region: string; revenue: number };

const { hostRef, value: rows } = useMarimoValue<MarimoTable<Row>>(
  "regional_rows",
);

return (
  <Slide>
    <span ref={hostRef} hidden mo-value="regional_rows" />
    <strong>{rows?.numRows ?? 0} regions</strong>
  </Slide>
);
```

Keep every projection host in authored TSX so Studio can inspect and authorize
its target. Treat `MarimoTable` as immutable. Use `getChild()`, `select()`, and
`toColumns()` for columnar work, and call `toArray()` when a component needs row
objects.

## Add dependencies

Use the Deno supplied by `marimo-studio[deno]` in the notebook's Python
environment so dependency updates and Studio builds use the same version.

Run from the view root so it updates `deno.json` and `deno.lock` together:

```console
uv run -- deno add --frozen=false --save-exact npm:reveal.js
```

Keep `minimumDependencyAge` and the frozen lockfile policy intact. Commit both
files after an intentional dependency update.

## Validate the presentation

Build through Marimo Studio, then inspect the rendered deck in a browser. Check
keyboard and control navigation, slide scaling, fragments, notebook results,
speaker-facing content, and narrow viewport behavior. The Studio build verifies
types and packages the deck before publishing it.

## Load remote font stylesheets

Link remote font stylesheets from `src/index.html` with
`<link rel="stylesheet">`. The Deno CSS bundler cannot load Google Fonts through
CSS `@import`. Linked stylesheets require browser network access and a hosting
policy that permits the stylesheet and font origins. Keep a fallback font in the
view's CSS.

## Link custom results to notebook inputs

Keep projection hosts explicit in authored source. Custom regions need every
kernel input, a readable label, and a rendering-source reference such as
`{"path":"src/App.tsx"}`. Keep these attributes on authored elements outside
native output subtrees. Follow the installed Studio skill's
`references/projections.md` for the shared contract:

```python
import marimo_studio.agent

print(marimo_studio.agent.skill().file("references/projections.md").read_text())
```

## Maintain project ignore rules

You own this view project's `.gitignore`. When adding libraries, extensions, or
build tools, ignore their generated files, caches, local configuration, and
secrets. Keep authored source, dependency manifests, and lockfiles tracked.
Studio supplies workspace rules for its own artifacts and locks. Check
`git status --short --ignored` after running new tooling and update the view's
ignore rules before committing.
