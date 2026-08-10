---
title: Revenue forecast
description: Run one reactive notebook as a focused revenue dashboard with native outputs and browser behavior.
---

# Revenue forecast

`examples/analysis.py` computes a quarterly forecast and presents an analyst
dashboard with scenario controls, forecast measures, interpretation, and
quarterly detail. The forecast definitions stay visible in notebook cells
while the view owns the dashboard layout and browser behavior.

Run the example from the repository root:

```console
uvx --with marimo-studio marimo edit examples/analysis.py --sandbox
```

Run the dashboard as an application:

```console
uvx --with marimo-studio marimo run examples/analysis.py --sandbox
```

Change the scenario or forecast quarter. Marimo reruns dependent cells and
updates each affected projection from the same notebook graph.

## What the notebook owns

- Source data and quarterly calculations
- Scenario and forecast-quarter controls
- Reactive dependencies
- Forecast measures, chart data, and briefing values
- Native tables and plots

## What the view owns

- Dashboard reading order
- Responsive layout and semantic theme
- Audience-specific labels and interpretation
- `app.js` behavior for the current briefing

Open **HTML & CSS** to inspect `index.html`, `app.css`, and `app.js`. The view
uses native cell projections, rich-output projections, `mo-value`, responsive
utility classes, semantic theme tokens, and a JavaScript module that reads the
current briefing.

::: info Compare the preview runtimes
Choose **Server** to run the view through the editor's Python session. Choose
**WebAssembly** to run a separate notebook instance in a Pyodide worker. Studio
synchronizes JSON-compatible values from matching native Marimo controls, then
each runtime evaluates its own reactive graph.
:::

Continue with [Use notebook results](../guide/notebook-results.md) for the
projection contracts or [Use HTML, CSS, and JavaScript](../guide/web-platform.md)
for the browser integration.
