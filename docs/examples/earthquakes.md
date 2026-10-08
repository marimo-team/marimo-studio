---
title: Earthquake watch
description: Compare a scrolling story, an operations map, a briefing deck, and a Quarto bulletin backed by one weekly earthquake notebook.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Earthquake watch

[`earthquakes.py`](https://github.com/marimo-team/marimo-studio/blob/main/examples/earthquakes.py)
loads a fixed USGS weekly feed with [Polars](https://pola.rs/), a dataframe
library for Python. It computes daily activity, a logarithmic magnitude
comparison, a descriptive frequency–magnitude fit, filtered event membership,
and one shared `seismic_analysis` value.

## Compare the views

<StudioExample family="earthquakes" />

Scroll **Story** to move through the map sequence. In **Operations**, raise the
minimum magnitude. The map, priority list, and summary resolve from 138 states
prepared from the notebook's magnitude and review-status controls.

In **Briefing**, use the comparison slider to recompute the amplitude and
energy ratios. Then change the catalog filter and watch the selected count and
epicenter map update inside the [Reveal.js](https://revealjs.com/)
presentation. On the frequency slide, move the magnitude threshold to compare
the observed cumulative count with the descriptive fit. The two lesson sliders
select notebook-computed rows in the browser, while the catalog controls filter
the projected weekly records. Press <kbd>Esc</kbd> to open the Reveal overview.

**Bulletin** is a long-form article rendered with
[Quarto](https://quarto.org/), a publishing system built on Pandoc. Quarto
supplies the title block and abstract, the table of contents, figure
cross-references, callouts, margin notes, and citations. The notebook supplies
every number in the running text, the magnitude and frequency passages embed
its controls, and Observable Plot draws the epicenter map, daily activity, and
Gutenberg–Richter figures from `seismic_analysis`.

Open **Notebook** to inspect the equations, fitted values, and reactive controls
that supply every view.

## Run locally

From the repository root:

```console
uv run marimo edit examples/earthquakes.py --sandbox
```

Studio opens `story`, the notebook's default view. Switch among `story`,
`operations`, `briefing`, and `bulletin`. The Bulletin renders with the
`quarto` command. Install [Quarto](https://quarto.org/docs/get-started/)
1.9.38 or newer, or prefix the command with `pixi run` to use the Quarto from
the repository's [pixi](https://pixi.prefix.dev/) environment. The notebook fetches
the pinned [GeoJSON](https://geojson.org/) map-data feed from
`raw.githubusercontent.com`. [MapLibre](https://maplibre.org/) renders the
maps, [Observable Plot](https://observablehq.com/plot/) renders the charts, and
Reveal.js supplies the presentation. Those libraries, fonts, and map styles can
add browser network requests.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/earthquakes.py)
- [Story](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/story)
- [Operations](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/operations)
- [Briefing](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/briefing)
- [Bulletin](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/bulletin)
