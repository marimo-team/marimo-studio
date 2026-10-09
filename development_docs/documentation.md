# Documentation delivery

`docs/` is the public product manual. `apps/docs` turns that source, verified
examples, and site configuration into the
[VitePress](https://vitepress.dev/) site deployed by
[GitHub Pages](https://docs.github.com/en/pages).

## Source ownership

| Source                                       | Owner                                                                          |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| `docs/`                                      | Public concepts, guides, examples, and reference                               |
| `apps/docs/.vitepress/routes.ts`             | Canonical page routes, navigation, and complete route inventory                |
| `apps/docs/.vitepress/config.mts`            | VitePress behavior, metadata, local search, theme, and base path               |
| `apps/docs/examples.ts`                      | Documentation example families, technologies, labels, and exported paths       |
| `apps/docs/scripts/build-examples.ts`        | Notebook and view export transaction                                           |
| `apps/docs/scripts/capture-thumbnails.ts`    | Gallery thumbnails captured from the published example views                   |
| `apps/docs/scripts/source-integrity.test.ts` | Page metadata, route inventory, and heading fragments                          |
| `apps/docs/scripts/verify-build.ts`          | Built routes, assets, base paths, examples, and sibling links                  |
| `tools/example-showcase/`                    | README showcase images composed from captured example views                    |
| `apps/docs/public/`                          | Brand, icon, screenshot, thumbnail, and showcase files plus generated examples |
| `development_docs/`                          | Contributor decisions, ownership, lifecycle, validation, and release workflow  |

Every public Markdown page must appear in `siteRoutes`. A new page also belongs
in the matching introduction, guide, example, or reference list so navigation,
sidebar labels, links, and route verification share one record.

## Public page shape

Write one page for one reader task or one reference contract:

1. Start with the feature, object, command, or decision.
2. Put the smallest working example before variants.
3. Explain the concrete objects visible in that example.
4. Keep caveats beside the affected command or API.
5. Link to deeper reference instead of repeating the architecture.

Use the product nouns from source: notebook, view, view project, Source,
artifact, presentation, Python runtime, Browser runtime, Prepared runtime,
projection, provider, and starter. Qualify revision, generation, document,
runtime, and session by their owner.

The root and package READMEs are compact gateways. They state the capability,
installation, first working commands, compatibility boundary, and canonical
documentation link. Detailed lifecycle and reference contracts belong in
`docs/`.

## Example families

`documentationExampleFamilies` is the allowlist for examples shipped with the
site. Each family names one notebook and every view exported from it.

`examples:build` creates a private staging directory, then for each family:

1. Exports the saved notebook with Marimo source and captured session data.
2. Exports every named view through `marimo-studio view export --json`.
3. Streams export progress from stderr while retaining stdout for the terminal
   result.
4. Validates schema, notebook, view, runtime, output, entrypoint, file count,
   static delivery preflight, relative document base, and relative asset URL
   policy.
5. Checks links to sibling views against the family allowlist.
6. Replaces that export's directory under `apps/docs/public/examples`. A failed
   export keeps its previous copy, and exports finished before it stay
   published. A complete run then removes exports the catalog no longer lists.

The published example tree contains one static notebook and one Prepared
runtime export per named view. Generated example files are build evidence.
Change the notebook, view source, provider lockfile, or example catalog, then
rebuild them through the documentation command.

## Notebook and view stack

`StudioViewStack` frames an example family's notebook export behind one of its
views. The tab rail chooses the document in front, and a click on the back layer
brings it forward. Both layers are live, scrollable iframes that load once the
stack nears the viewport. Containers narrower than 36rem show one flat layer at
a time.

```md
<StudioViewStack family="quadratic-programs" />
```

## View masonry

`StudioViewMasonry` lays out every view in `documentationExampleFamilies` as a
column masonry of posters on the landing page, interleaving families so
neighboring tiles come from different notebooks. Each tile links to its
example page with the view selected.

```md
<StudioViewMasonry />
```

Each catalog view declares a `poster` shape. Use `tall` for pages that scroll
past one screen and `wide` for single-screen apps and decks.
`documentationPosterViewports` maps each shape to its capture viewport, and the
component uses the same size to reserve the tile before the image loads.

## Example thumbnails and posters

The Examples page renders one `StudioExampleCard` per family. Each card cycles
through `apps/docs/public/thumbnails/FAMILY/VIEW.webp` for the views listed in
`documentationExampleFamilies`. The landing page masonry reads
`apps/docs/public/posters/FAMILY/VIEW.webp`. Thumbnails and posters are
committed assets. Recapture them after a visible view change or when a view
joins the catalog:

```console
make docs-thumbnails
```

The target exports the examples when `apps/docs/public/examples` is missing and
installs Chromium. The script serves `apps/docs/public` locally, opens each
exported view at 1440x900 and device scale 2, waits for network idle, loaded
fonts, and a settle delay, then writes a 1600px wide WebP thumbnail. It then
resizes the same page to the view's poster viewport, waits again, and writes a
1024px wide WebP poster. Select views with `--family SLUG` or
`--view FAMILY/VIEW`, or capture a deployed site with `--base-url`:

```console
pnpm --filter @marimo-studio/docs thumbnails -- --view athletes/field
pnpm --filter @marimo-studio/docs thumbnails -- --base-url https://marimo-team.github.io/marimo-studio/
```

A view that fails to load is reported and the remaining views are still
captured. Inspect the images before committing them.

## Example showcase images

The README opens with `apps/docs/public/showcase/marimo-studio-wall-THEME.webp`,
which places every example notebook above its views on a receding plane. Each
family also has a fan, `marimo-studio-fan-FAMILY-THEME.webp`, with the notebook
raised behind its views. Every image has `light` and `dark` variants for
GitHub's color schemes and keeps a transparent background. The plain file is a
2400px WebP at quality 0.9 for READMEs and pages, and the `@2x` file is the
4800px lossless master. Render them again after a visible view change or when
the catalog changes:

```console
make docs-showcase
```

The target exports the examples when `apps/docs/public/examples` is missing.
`tools/example-showcase/capture.ts` serves `apps/docs/public`, opens each
exported notebook and view at 1440x900 and device scale 3, waits for network
idle, loaded fonts, and a settle delay, then writes a PNG to the ignored
`tools/example-showcase/shots/` directory. `render.ts` composes each entry in
`showcases.json` through `compose.html` on a 2400px canvas. It rasterizes the
canvas at the largest output `scale` times `supersample`, then resamples it
with Chromium's high-quality filter to each entry in `outputs`, largest first.
`compose.html` loads Inter and JetBrains Mono from jsDelivr, so rendering needs
network access. Card headers take notebook files, view labels, and technologies
from `apps/docs/examples.ts`.

Pass `FAMILY/VIEW` arguments to capture selected shots and showcase names to
render a subset. A fan uses its family's shots and the wall uses every shot.
`render.ts` names the capture command for any shot a selected showcase is
missing:

```console
node tools/example-showcase/capture.ts quadratic-programs/lab
node tools/example-showcase/render.ts marimo-studio-fan-quadratic-programs
```

## Build and serve

Build the complete site with:

```console
make docs-build
```

The target checks the prepared Marimo frontend, builds browser assets, runs
documentation source tests, exports examples, builds VitePress, and verifies
the final directory.

Serve the same source locally with:

```console
make docs-serve
```

The server starts immediately and serves the examples already exported to
`apps/docs/public/examples`. It lists any missing exports when it starts. Run
`make docs-examples` alongside it, and each example appears on reload once its
export finishes.

[Portless](https://portless.sh/) assigns the VitePress server an available port
and exposes it at `https://docs.marimo-studio.localhost/`. Linked Git worktrees
receive a branch prefix, so each running workspace has its own URL. Use the URL
printed by `make docs-serve`. On its first HTTPS run from a terminal, Portless
may request local administrator access to bind port 443 and trust its local
certificate authority. Without a terminal, such as from a coding agent, the
target reuses a proxy already listening on port 443 or starts one on port 1355,
and the printed URL includes `:1355`.

Preview an existing `make docs-build` artifact with:

```console
make docs-preview
```

Preview uses `https://preview.docs.marimo-studio.localhost/`, with the same
worktree prefix policy. Development and preview can run together. Both commands
pass Portless's assigned `PORT` to VitePress; use the printed URL to open them.
The internal `dev:server` and `preview:server` scripts require `PORT` explicitly.

The development server uses an empty deployment base. Inspect the landing page,
changed pages, navigation, search, code blocks, tables, examples, and local
links at desktop and narrow widths.

Run `make docs-examples` when iterating on exported example inputs. It builds
the browser assets first, then exports every notebook and view, about two
minutes per view. Pass selectors in `EXAMPLES` to export only what changed:

```console
make docs-examples EXAMPLES='--family athletes'
make docs-examples EXAMPLES='--notebook earthquakes'
make docs-examples EXAMPLES='--view occupancy/monitor --view athletes/field'
```

Selectors may be repeated and combined. `--family` selects its notebook and
every view. `--notebook` selects one notebook export. `--view` accepts an exact
`FAMILY/VIEW` identity. Each selected export replaces only its own directory.
`examples:check` validates that the publication is complete.

## Build verification

Source tests require:

- Every Markdown page has a title and description.
- Every Markdown page has one route.
- Installation examples resolve the current Studio release.
- Heading fragments resolve.

Final build verification requires:

- Local Markdown targets exist.
- Route paths are unique.
- Every route produced its expected HTML file.
- Navigation links use the configured base path.
- Generated scripts, styles, icons, and authored assets stay under that base.
- Every example contains its entrypoint, runtime configuration, runtime asset,
  and `.nojekyll` marker.
- Static notebook exports retain source and filename metadata.
- View exports use a document-relative base and link to existing siblings.
- Every example view has a gallery thumbnail.
- Documentation index links stay under the deployment base and resolve to
  generated Markdown files.

The site also emits canonical metadata, local search data, `llms.txt`, and
`llms-full.txt` through VitePress and its configured plugin. Inspect those files
after changing site metadata or build plugins.
The LLM plugin receives the site origin and adds VitePress's base path itself.
The Python package exposes the published `llms.txt` as its `Documentation Index`
project URL, which `agent-plugins read marimo-studio` includes in the briefing.

## Deployment

`.github/workflows/pages.yml` exports each example family in its own job with
`examples:build --family SLUG`. A final job downloads the families,
runs `examples:check` to validate the assembled publication, and builds the
site. A `main` build receives the base path from GitHub Pages, uploads
`apps/docs/.vitepress/dist`, then deploys that exact artifact.

Pull requests that change the site or its examples build the complete
root-based site. Pull requests that change product code run `examples:smoke`,
which exports three views through the same export path: the Earthquake watch
story (plain HTML), its briefing (React), and the Quadratic programs report
(Typst). `make docs-build` builds the complete site locally.

## Version parity

A release declares its version in `packages/marimo-studio/pyproject.toml` and
`uv.lock`. Installation examples use `marimo-studio` or `marimo-studio[deno]`
to resolve the current release. Review these communication surfaces together:

- Root `README.md`
- `packages/marimo-studio/README.md`
- Public installation, compatibility, configuration, provider, and workflow
  pages under `docs/`
- `skills/marimo-studio/SKILL.md`
- `.github/release-notes/vX.Y.Z.md`

Keep compatibility claims aligned with `_compat/release.json`, Python package
metadata, provider extras, and browser build metadata. Release notes and
migration guidance name the versions whose behavior they describe.

## Change checklist

1. Verify the claim against current source, commands, examples, and tests.
2. Edit the owning public or contributor page.
3. Update route or example inventories when the source set changes.
4. Keep README gateway claims aligned with the canonical public guide.
5. Run `make docs-build`.
6. Inspect the rendered site at desktop and narrow widths.
7. Run `make e2e` when documentation depends on changed browser behavior.
8. Run `make package` when packaged docs, skills, browser assets, or examples
   enter the distribution contract.
