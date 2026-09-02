---
title: Earthquake watch
description: Compare a story, operations map, and briefing deck backed by one weekly earthquake notebook.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Earthquake watch

[`earthquakes.py`](https://github.com/marimo-team/marimo-studio/blob/main/examples/earthquakes.py)
loads a fixed USGS weekly feed with [Polars](https://pola.rs/), a dataframe
library for Python. It defines magnitude and review controls, a filtered event
table, daily activity, weekly totals, and a priority watchlist.

## Compare the views

<StudioExample family="earthquakes" />

Scroll **Story** to move through the map sequence. In **Operations**, raise the
minimum magnitude. The map, priority list, and summary update from the same
reactive filter.

In **Briefing**, move to the operating-picture slide and change the control.
The dependent measures update inside the [Reveal.js](https://revealjs.com/)
presentation.

Open **Notebook** to trace the filter from its Marimo control to the tables and
summaries consumed by all three views.

## Run locally

From the repository root:

```console
uv run marimo edit examples/earthquakes.py --sandbox
```

Open Studio from the marimo editor, then switch among `story`, `operations`,
and `briefing`. The notebook fetches the pinned
[GeoJSON](https://geojson.org/) map-data feed from
`raw.githubusercontent.com`. [MapLibre](https://maplibre.org/) renders the
maps, [Observable Plot](https://observablehq.com/plot/) renders the charts, and
Reveal.js supplies the presentation. Those libraries, fonts, and map styles can
add browser network requests.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/earthquakes.py)
- [Scrollytelling story](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/story)
- [Operations map](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/operations)
- [Briefing deck](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/briefing)

Reveal.js keeps navigation, fragments, overview, and keyboard controls inside
the briefing presentation.
