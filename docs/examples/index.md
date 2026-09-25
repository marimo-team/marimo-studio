---
title: Examples
description: Compare twelve live views backed by four Marimo notebooks.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Examples

Four notebooks back twelve live views. Open a family to compare one analysis
presented as a lecture, explainer, lab, report, dashboard, story, map, slide
deck, or PDF.

<div class="studio-example-gallery">
  <StudioExampleCard family="quadratic-programs">A lecture deck, a reading explainer, and an interactive geometry lab.</StudioExampleCard>
  <StudioExampleCard family="athletes">A report, a linked Mosaic dashboard, and Three.js slides.</StudioExampleCard>
  <StudioExampleCard family="earthquakes">A scroll-driven story, a map, and Reveal.js slides.</StudioExampleCard>
  <StudioExampleCard family="occupancy">A monitoring dashboard, an interactive model report, and a printable PDF.</StudioExampleCard>
</div>

## Run an example locally

From the repository root, open one example notebook:

```console
uv run marimo edit examples/quadratic_program.py --sandbox
```

Replace `quadratic_program.py` with `athletes.py`, `earthquakes.py`, or
`occupancy.py` to open another family. Studio discovers the view projects stored beside each notebook. The
examples fetch pinned datasets and can load fonts, maps, or remote modules
declared by their view source.
