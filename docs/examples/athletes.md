---
title: Rio 2016 athletes
description: Compare an overview report, a Mosaic explorer, a Three.js field presentation, and a Quarto paper with live equations backed by one Rio 2016 athlete notebook.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Rio 2016 athletes

[`athletes.py`](https://github.com/marimo-team/marimo-studio/blob/main/examples/athletes.py)
loads the Rio 2016 roster with [Polars](https://pola.rs/), a dataframe library
for Python. It calculates age, medal awards, sport participation, and athlete
profiles, and fits how body mass scales with height. One notebook backs
every view.

## Compare the views

<StudioExample family="athletes" />

In **Overview**, change **Sport**. The native marimo control selects one of 29
prepared notebook states. Four `mo-value` totals, the browser-drawn roster, and
the `top_sports` chart update from that result.

In **Explorer**, select a sport bar or brush an age range.
[Mosaic](https://uwdata.github.io/mosaic/) coordinates that browser-side
selection while the notebook remains the source of the complete athlete table.

In **Field**, move through the roster as a four-chapter
[Three.js](https://threejs.org/) 3D presentation. The same records regroup by
sport, medal status, height, weight, and age. Its sport control uses the same
29 prepared states as Overview.

In **Paper**, change **Sport** to refit a short note on how body mass scales
with stature. [Quarto](https://quarto.org/), a publishing system built on
Pandoc, renders its numbered equations, theorem environments,
cross-references, and bibliography, and [KaTeX](https://katex.org/) typesets
the math in the browser. The results table and the running text read the
notebook's fitted values, and one projected cell writes the fitted lines with
marimo's own LaTeX beside Quarto's math.

Open **Notebook** to inspect the controls and Polars operations in their
analytical context.

## Run locally

From the repository root:

```console
uv run marimo edit examples/athletes.py --sandbox
```

Studio opens `overview`, the notebook's default view. Switch among `overview`,
`explorer`, `field`, and `paper`. The Paper renders with the `quarto` command.
Install [Quarto](https://quarto.org/docs/get-started/) 1.9.38 or newer, or
prefix the command with `pixi run` to use the Quarto from the repository's
[pixi](https://pixi.prefix.dev/) environment. KaTeX loads from a CDN, so the
Paper needs no TeX installation. The notebook fetches the pinned athlete CSV from
`raw.githubusercontent.com`. The Explorer and Field views also load the
remote font or module origins declared by their view source.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/athletes.py)
- [Overview](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/overview)
- [Explorer](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/explorer)
- [Field](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/field)
- [Paper](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/athletes/paper)
