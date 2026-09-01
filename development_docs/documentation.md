# Documentation delivery

`docs/` is the public product manual. `apps/docs` turns that source, verified
examples, and site configuration into the
[VitePress](https://vitepress.dev/) site deployed by
[GitHub Pages](https://docs.github.com/en/pages).

## Source ownership

| Source                                       | Owner                                                                         |
| -------------------------------------------- | ----------------------------------------------------------------------------- |
| `docs/`                                      | Public concepts, guides, examples, and reference                              |
| `apps/docs/.vitepress/routes.ts`             | Canonical page routes, navigation, and complete route inventory               |
| `apps/docs/.vitepress/config.mts`            | VitePress behavior, metadata, local search, theme, and base path              |
| `apps/docs/examples.ts`                      | Documentation example families, technologies, labels, and exported paths      |
| `apps/docs/scripts/build-examples.ts`        | Notebook and view export transaction                                          |
| `apps/docs/scripts/source-integrity.test.ts` | Page metadata, release pins, route inventory, and heading fragments           |
| `apps/docs/scripts/verify-build.ts`          | Built routes, assets, base paths, examples, and sibling links                 |
| `apps/docs/public/`                          | Authored brand, icon, and screenshot assets plus generated examples           |
| `development_docs/`                          | Contributor decisions, ownership, lifecycle, validation, and release workflow |

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
artifact, presentation, Python runtime, Browser runtime, projection, provider,
and starter. Qualify revision, generation, document, runtime, and session by
their owner.

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
3. Validates schema, notebook, view, runtime, output, entrypoint, file count,
   relative document base, and relative asset URL policy.
4. Checks links to sibling views against the family allowlist.
5. Replaces `apps/docs/public/examples` as one directory transaction.

The published example tree contains one static notebook and one Browser runtime
export per named view. Generated example files are build evidence. Change the
notebook, view source, provider lockfile, or example catalog, then rebuild them
through the documentation command.

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

The development server runs at `http://127.0.0.1:4173/` with an empty
deployment base. Inspect the landing page, changed pages, navigation, search,
code blocks, tables, examples, and local links at desktop and narrow widths.

Run `make docs-examples` when iterating on exported example inputs. Run
`make build` first when presentation or Browser runtime assets changed.

## Build verification

Source tests require:

- Every Markdown page has a title and description.
- Every Markdown page has one route.
- Public release pins match the package version.
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

The site also emits canonical metadata, local search data, `llms.txt`, and
`llms-full.txt` through VitePress and its configured plugin. Inspect those files
after changing site metadata or build plugins.

## Deployment

`.github/workflows/pages.yml` runs `make docs-build` for pull requests and
`main`. A `main` build receives the base path from GitHub Pages, uploads
`apps/docs/.vitepress/dist`, then deploys that exact artifact.

Pull requests prove the production build. Deployment occurs from `main` after
the build job succeeds.

## Version parity

A release version appears in several public source surfaces. Update and review
them as one release unit:

- `packages/marimo-studio/pyproject.toml`
- `uv.lock`
- `apps/e2e/fixtures-provider/provider/pyproject.toml`
- Root `README.md`
- `packages/marimo-studio/README.md`
- Public installation, compatibility, configuration, provider, and workflow
  pages under `docs/`
- `skills/marimo-studio/SKILL.md`
- `.github/release-notes/vX.Y.Z.md`

Keep compatibility claims aligned with `_compat/release.json`, Python package
metadata, provider extras, and browser build metadata. Search for the prior
version across the tracked public sources before release.

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
