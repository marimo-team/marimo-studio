---
title: Examples
description: Compare the views that share one marimo notebook per example.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Examples

Each example notebook backs four views, from lecture decks and linked
explorers to Quarto articles and Typst and LaTeX PDFs. Open an example to
compare how each view presents one analysis. The published views are Prepared
exports, so they run without a Python kernel.

<div class="studio-example-gallery">
  <StudioExampleCard family="quadratic-programs">A lecture deck, a reading explainer, an interactive geometry lab, and a typeset Typst report.</StudioExampleCard>
  <StudioExampleCard family="athletes">An overview report, a linked Mosaic explorer, a Three.js field presentation, and a Quarto paper.</StudioExampleCard>
  <StudioExampleCard family="earthquakes">A scroll-driven story, an operations map, a Reveal.js briefing, and a Quarto bulletin.</StudioExampleCard>
  <StudioExampleCard family="occupancy">A room monitor, a pdfcn PDF report, a LaTeX journal paper, and an interactive model review.</StudioExampleCard>
</div>

## Run an example locally

From the repository root, open one example notebook:

```console
uv run marimo edit examples/quadratic_program.py --sandbox
```

Replace `quadratic_program.py` with `athletes.py` or `earthquakes.py` to open
another example. Studio discovers the view projects stored beside each
notebook. Each example page lists the tools its views need.
[Building occupancy](occupancy.md#run-locally) declares Tectonic for its LaTeX
paper and opens with `--sandbox=pixi`. The examples fetch pinned datasets and
can load fonts, maps, or remote modules declared by their view source.
