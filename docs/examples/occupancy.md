---
title: Building occupancy
description: Compare a facilities monitor and an interactive model review backed by one room-sensor notebook.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Building occupancy

[`occupancy.py`](https://github.com/marimo-team/marimo-studio/blob/main/examples/occupancy.py)
backs both views. It loads the UCI Occupancy Detection training split with
Polars and defines rolling sensor baselines, anomaly candidates, a transparent
occupancy score, and a threshold sweep.

## Compare monitoring with model review

<StudioExample family="occupancy" />

Change **Signal** in the monitor. Marimo recomputes the selected series while
ECharts keeps the trend, baseline, anomalies, and current summary together.

Switch to **Model review** and move the threshold. Accuracy, precision, recall,
the curve marker, confusion counts, and error evidence update from the same
notebook score.

Open **Notebook** to inspect the rolling calculations and threshold evaluation
that both views present.

## Read the source

- [Facilities monitor](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/monitor)
- [Model review](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/model-review)

Both views keep statistical definitions in the notebook. Their component code
formats and presents those results for separate decisions.
