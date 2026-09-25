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
loads the Rio 2016 roster with [Polars](https://pola.rs/), a dataframe library
for Python, and calculates age, medal awards, sport participation, and athlete
profiles. One notebook backs all three views.

## Compare the views

<StudioExample family="athletes" />

In **Report**, change **Sport**. The native Marimo control selects one of 29
prepared notebook states. Four `mo-value` totals, the browser-drawn roster, and
the `top_sports` chart update from that result.

In **Dashboard**, select a sport bar or brush an age range.
[Mosaic](https://uwdata.github.io/mosaic/) coordinates that browser-side
selection while the notebook remains the source of the complete athlete table.

In **Slides**, move through the roster as a four-chapter
[Three.js](https://threejs.org/) 3D presentation. The same records regroup by
sport, medal status, height, weight, and age. Its sport control uses the same
29 prepared states as Report.

Open **Notebook** to inspect the controls and Polars operations in their
analytical context.

## Run locally

From the repository root:

```console
uv run marimo edit examples/athletes.py --sandbox
```

Open Studio from the marimo editor, then switch among `overview`, `explorer`,
and `field`. The notebook fetches the pinned athlete CSV from
`raw.githubusercontent.com`. The explorer and field briefing also load the
remote font or module origins declared by their view source.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/athletes.py)
- [Report view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/overview)
- [Dashboard view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/explorer)
- [Slides view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/field)

The three views use sibling-relative URLs, so their links survive a deployment
base path and a copied parent directory.
