---
title: Rio 2016 athletes
description: Compare a publication report, linked Mosaic explorer, and Three.js briefing backed by one Rio 2016 athlete notebook.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Rio 2016 athletes

[`athletes.py`](https://github.com/marimo-team/marimo-studio/blob/main/examples/athletes.py)
backs all three views. It loads the Rio 2016 roster with Polars, calculates age
and medal awards, and produces summaries for sport participation and athlete
profiles.

## Compare the report, explorer, and field briefing

<StudioExample family="athletes" />

Change **Sport** in the report. The native Marimo control reruns its dependent
cell, then the four totals and rendered Polars table update in place.

Open **Notebook** to read the same control and dependent Polars operations in
their analytical context.

Switch to **Explorer** and select a sport bar or brush an age range. Mosaic owns
that browser-side selection. The notebook remains the source of the complete
athlete table.

Open **Field briefing** to move through the roster as a four-chapter Three.js
presentation. The same athlete records regroup by sport, medal status, height,
weight, and age.

## Read the source

- [Report view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/overview)
- [Explorer view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/explorer)
- [Field briefing](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/field)

All three views link to one another with sibling-relative URLs. The links work
at a local root, beneath a documentation base path, and in a copied static
directory.
