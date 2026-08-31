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
backs all three views. It loads a fixed USGS weekly feed with Polars and defines
magnitude and review controls, a filtered event table, daily activity, weekly
totals, and a priority watchlist.

## Compare the story, map, and deck

<StudioExample family="earthquakes" />

Scroll the **Story** to move through the map sequence. Open **Operations** and
raise the minimum magnitude. The map, priority list, and summary update from the
same reactive filter. Open **Briefing**, move to the operating-picture slide,
and change the control again. The dependent measures beneath it update inside
the deck.

Open **Notebook** to trace that filter from its Marimo control to the tables and
summaries consumed by all three presentations.

## Read the source

- [Scrollytelling story](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/story)
- [Operations map](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/operations)
- [Briefing deck](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/earthquakes/briefing)

The story links to all three sibling exports with relative URLs. Reveal.js keeps
its navigation, fragments, overview, and keyboard controls inside the briefing
frame.
