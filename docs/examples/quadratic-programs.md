---
title: Quadratic programs
description: Compare a lecture deck, a reading explainer, and an interactive geometry lab backed by one quadratic program notebook.
sidebar: false
aside: false
outline: false
pageClass: studio-example-page
---

# Quadratic programs

[`quadratic_program.py`](https://github.com/marimo-team/marimo-studio/blob/main/examples/quadratic_program.py)
states a small quadratic program with [CVXPY](https://www.cvxpy.org/), a Python
library for convex optimization. It solves the program for four shapes of the
objective and every direction of its linear term. Cell by cell, the notebook
holds the argument of a short lesson: the standard form, why the problem
matters, its geometry, duality, and the key ideas. One notebook backs all three
views.

## Compare the views

<StudioExample family="quadratic-programs" />

**Lecture** is a [Reveal.js](https://revealjs.com/) deck. Each slide projects
one notebook cell or draws from the notebook's `region`, `bowl`, and `solution`
values. Step through the two-dimensional example to add the walls, the feasible
region, the level curves, and the solution in turn. On the next slide, change
the shape of _P_ and the direction of _q_ with the notebook's own controls.

**Explainer** is a single HTML page. Its reading column projects the notebook's
Markdown, while the figure, the solution summary, and a table of dual values stay
beside it. The native **Shape of P** and **Direction of q** controls select one
of 48 prepared notebook states.

**Lab** is a [Svelte](https://svelte.dev/) app drawn with
[D3](https://d3js.org/). Drag around the dial to turn _q_. The notebook's
`sweep` records the solution for 180 directions, so the optimum, the level
curves, the chart, and the active constraints update in the browser.
**Shape of P** selects one of four prepared states.

Open **Notebook** to read the analysis the three views share.

## Run locally

From the repository root:

```console
uv run marimo edit examples/quadratic_program.py --sandbox
```

Studio opens the Explainer, the notebook's default view. The Lecture and Lab
views build with the Deno toolchain supplied by `marimo-studio[deno]`. All three
views load their fonts from jsDelivr.

## Read the source

- [Notebook](https://github.com/marimo-team/marimo-studio/blob/main/examples/quadratic_program.py)
- [Lecture view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/quadratic_program/lecture)
- [Explainer view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/quadratic_program/explainer)
- [Lab view](https://github.com/marimo-team/marimo-studio/tree/main/examples/__marimo__/studio/quadratic_program/lab)

The notebook adapts the
[quadratic program notebook](https://github.com/marimo-team/learn/blob/main/optimization/04_quadratic_program.py)
from marimo's learn repository, published under the
[MIT License](https://github.com/marimo-team/learn/blob/main/LICENSE).
