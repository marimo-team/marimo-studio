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
loads the UCI Occupancy Detection training split with
[Polars](https://pola.rs/), a dataframe library for Python. It defines rolling
sensor baselines, anomaly candidates, a transparent occupancy score, and a
threshold sweep.

## Compare the views

<StudioExample family="occupancy" />

In **Monitor**, change **Signal**. Marimo recomputes the selected series while
[ECharts](https://echarts.apache.org/) renders the trend, baseline, anomalies,
and current summary together.

In **Model review**, move the threshold. Accuracy, precision, recall, the curve
marker, confusion counts, and error evidence update from the same notebook
score. [Recharts](https://recharts.org/) renders the threshold curve as a React
component.

Open **Notebook** to inspect the rolling calculations and threshold evaluation
that both views present.

## Run locally

From the repository root:

```console
uv run marimo edit examples/occupancy.py --sandbox
```

Open Studio from the marimo editor, then switch between `monitor` and
`model-review`. The notebook fetches the pinned occupancy CSV from
`raw.githubusercontent.com`. The Browser runtime also needs
[Pyodide](https://pyodide.org/), the Python distribution that runs in the
browser, and its Python packages on an uncached run.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/occupancy.py)
- [Facilities monitor](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/monitor)
- [Model review](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/model-review)

Both views keep statistical definitions in the notebook. Their component code
formats and presents those results for separate decisions.
