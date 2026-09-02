---
title: Examples
description: Compare nine live views backed by three Marimo notebooks.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# One notebook, many views

Three notebooks back nine live views. Open a family to compare the same
analysis as a report, explorer, story, map, monitor, model review, or deck.

<div class="studio-example-catalog">
  <a href="./athletes">
    <strong>Rio 2016 athletes</strong>
    <p>A publication report, linked Mosaic explorer, and Three.js briefing.</p>
    <small>Vanilla HTML · Svelte · Mosaic · Three.js</small>
  </a>
  <a href="./earthquakes">
    <strong>Earthquake watch</strong>
    <p>A scroll-driven story, an operations map, and a briefing deck.</p>
    <small>Observable Plot · MapLibre · Reveal.js</small>
  </a>
  <a href="./occupancy">
    <strong>Building occupancy</strong>
    <p>A facilities monitor, interactive model review, and printable field report.</p>
    <small>ECharts · Recharts · React PDF · Marimo controls</small>
  </a>
</div>

## Run an example locally

From the repository root, open one example notebook:

```console
uv run marimo edit examples/athletes.py --sandbox
```

Replace `athletes.py` with `earthquakes.py` or `occupancy.py` to open another
family. Studio discovers the view projects stored beside each notebook. The
examples fetch pinned datasets and can load fonts, maps, or remote modules
declared by their view source.
