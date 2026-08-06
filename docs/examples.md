---
title: Examples
description: Run a compact revenue forecast and a three-view collection research workflow.
---

# Examples

The repository includes a compact authoring example and a realistic research
workflow. Both keep computation in an ordinary Marimo notebook and place
audience-specific presentation in Studio view files.

## Revenue forecast

`examples/analysis.py` computes one quarterly forecast and presents an analyst
dashboard with scenario controls, forecast measures, interpretation, and
quarterly detail.

Run it from the repository root:

```console
make install build
uv run marimo edit examples/analysis.py --no-sandbox
```

Change the scenario or forecast quarter and watch every dependent measure,
summary, and table update from the same notebook graph.

Open **HTML & CSS** to inspect the authored files. The dashboard demonstrates
responsive utilities, semantic theme tokens, native cell projections,
`mo-value`, and a short `app.js` module that copies the current briefing.

## Collection research packet

`examples/nga_collection.py` turns pinned National Gallery of Art Open Data
records into a six-work research packet:

| View       | Task                                                                                 |
| ---------- | ------------------------------------------------------------------------------------ |
| **Corpus** | Inspect source transformations and narrow the collection by year, medium, or creator |
| **Study**  | Review matching images and select six works in order                                 |
| **Packet** | Check the exact selection, provenance, and downloadable handoff                      |

Run it from the repository root:

```console
uv run --with pyobservablejs --with polars \
  marimo edit examples/nga_collection.py --no-sandbox
```

The first run downloads CSV files from a pinned revision of the NGA Open Data
repository. The notebook enables Marimo's native lazy cell cache. Cacheable
cell results are reused across runs. Values that cannot be serialized execute
normally.

Follow one complete workflow:

1. Open **Corpus** and narrow the collection.
2. Switch to **Study** with the same filters and kernel.
3. Select six works in the gallery.
4. Open **Packet** and verify the ordered selection.
5. Download the packet.
6. Change one attribution or corpus rule in the notebook and inspect every
   affected view.

The three views preserve filters and selection state because Marimo owns the
live controls and reactive graph. Each view contributes its own reading order,
theme, and task-specific composition.

Continue with [Design a view](design-views.md) to apply these patterns to an
existing notebook.
