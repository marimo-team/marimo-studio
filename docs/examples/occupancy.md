---
title: Building occupancy
description: Compare a room monitor, a pdfcn PDF report, a LaTeX journal paper, and a model review backed by one room-sensor notebook.
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

In **Field report**, choose one of the three prepared scopes. The React view lays
out the notebook's `occupancy_analysis` snapshot with
[pdfcn](https://github.com/shadcn-labs/pdfcn), a set of shadcn-style PDF
components, as a room-use summary, a sensor comparison, and the occupancy-score
evidence. [Takumi](https://takumi.kane.tw/docs/pdf), a WebAssembly layout
engine, renders the three A4 pages to a vector PDF in the browser, and the view
shows them beside a download link.

In **Journal paper**, the notebook argues its occupancy score as a short
[LaTeX](https://www.latex-project.org/) paper in the journal template of
[IEEE TVCG](https://www.computer.org/csdl/journal/tg), the IEEE Transactions on
Visualization and Computer Graphics. [Tectonic](https://tectonic-typesetting.github.io/), a
self-contained TeX engine, typesets it from the notebook's own results: its
matplotlib figures as vector graphics drawn at the width of the page's columns,
its daily, sensor, and error-episode dataframes as tables, and its numbers and
dates in prose formatted by the paper. Sentences switch with the data, so the
off-hours scope, which has no occupied readings, reads correctly too. Run the notebook locally and change **Scope** or
**Occupancy threshold** in Notebook, and Studio typesets the paper again.

In **Model review**, choose one of three prepared scopes and move the threshold
across 17 notebook-computed operating points. Threshold changes update
accuracy, precision, recall, the curve marker, confusion counts, and error
evidence in the browser. [Recharts](https://recharts.org/) renders the threshold
curve as a React component.

Open **Notebook** to inspect the rolling calculations, room profiles, and
threshold evaluation that every view presents.

## Run locally

From the repository root:

```console
uv run marimo edit examples/occupancy.py --sandbox
```

Studio opens `monitor`, the notebook's default view. Switch among `monitor`,
`pdf-report`, `paper`, and `model-review`. The notebook fetches the pinned
occupancy CSV from `raw.githubusercontent.com`, and the Field report loads
Takumi's WebAssembly module from jsDelivr. The Journal paper compiles with the
`tectonic` command. Install Tectonic with `pixi global install tectonic`, or
start marimo with `pixi run` from the repository root, whose pixi environment
provides it. The first compile downloads the TeX packages the paper uses and
can outlast a build, so run `pixi run --locked ./scripts/fetch-tex-packages.sh`
once before opening the view. The Browser runtime also needs
[Pyodide](https://pyodide.org/), the Python distribution that runs in the
browser, and its Python packages on an uncached run.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/occupancy.py)
- [Monitor](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/monitor)
- [Field report](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/pdf-report)
- [Journal paper](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/paper)
- [Model review](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/occupancy/model-review)
