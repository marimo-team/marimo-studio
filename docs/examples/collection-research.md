---
title: Collection research
description: Run one notebook through three views for corpus discovery, visual study, and packet preparation.
---

# Collection research

`examples/nga_collection.py` turns pinned National Gallery of Art Open Data
records into a six-work research packet. One notebook preserves source
transformations, selection rules, and provenance while three views support
discovery, study, and handoff.

Run the example from the repository root:

```console
uvx --with marimo-studio marimo edit examples/nga_collection.py --sandbox
```

Run the default corpus view as an application:

```console
uvx --with marimo-studio marimo run examples/nga_collection.py --sandbox
```

::: info First run
The first run downloads comma-separated value files from a pinned revision of
the NGA Open Data repository.
:::

## Follow the workflow

| View       | Task                                                                                 |
| ---------- | ------------------------------------------------------------------------------------ |
| **Corpus** | Inspect source transformations and narrow the collection by year, medium, or creator |
| **Study**  | Review matching images and select six works in order                                 |
| **Packet** | Check the selection, provenance, and downloadable handoff                            |

1. Open **Corpus** and narrow the collection.
2. Switch to **Study** with the same filters and kernel.
3. Select six works in the gallery.
4. Open **Packet** and verify the ordered selection.
5. Download the packet.
6. Change an attribution or corpus rule in the notebook and inspect each
   affected view.

## What the notebook owns

- Source acquisition and normalization
- Corpus filters and selected records
- Image and provenance data
- Ordered selection state
- Packet generation and download

## What the views own

- Separate routes for discovery, study, and handoff
- Task-specific reading order and controls
- Responsive gallery and packet layouts
- View-specific semantic themes

The three views project the same live controls and reactive graph. Switching a
view keeps the current browser session, filters, and ordered selection.

Continue with [Create and manage views](../guide/views.md) to build another
multi-view workflow from one notebook.
