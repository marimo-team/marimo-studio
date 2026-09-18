---
title: Building occupancy
description: Compare a facilities monitor, model review, and printable field report backed by one room-sensor notebook.
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

In **Monitor**, choose an observation scope and signal. The controls resolve 12
prepared combinations. [Observable Notebook Kit](https://observablehq.com/notebook-kit/kit)
connects those results to [Observable Plot](https://observablehq.com/plot/) charts
in a field-notebook layout, updating the signal, baseline, anomalies, and summary together.

In **Model review**, choose one of three prepared scopes and move the threshold
across 17 notebook-computed operating points. Threshold changes update
accuracy, precision, recall, the curve marker, confusion counts, and error
evidence in the browser. [Recharts](https://recharts.org/) renders the threshold
curve as a React component.

In **PDF report**, choose one of the three prepared scopes. The React view
composes the notebook-owned room profile and model evidence into an A4 report,
then generates the downloadable PDF in the browser.

Open **Notebook** to inspect the rolling calculations, room profiles, and
threshold evaluation that all three views present.

## Run locally

From the repository root:

```console
uv run marimo edit examples/occupancy.py --sandbox
```

Open Studio from the marimo editor, then switch among `monitor`, `model-review`,
and `pdf-report`. The notebook fetches the pinned occupancy CSV from
`raw.githubusercontent.com`. The Browser runtime also needs
[Pyodide](https://pyodide.org/), the Python distribution that runs in the
browser, and its Python packages on an uncached run.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/occupancy.py)
- [Facilities monitor](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/monitor)
- [Model review](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/model-review)
- [PDF field report](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/pdf-report)

All three deployed views use prepared states and run without a Python kernel.
They keep statistical definitions in the notebook. Their presentation
code formats and presents those results for separate decisions.
