---
title: Examples
description: Run one National Gallery of Art notebook through vanilla, React, and Svelte views.
---

# Examples

`examples/nga.py` analyzes National Gallery of Art Open Data through one
reactive Marimo notebook. Three Studio views present that notebook as a
collection brief, an artwork browser, and an editorial story.

## NGA collection explorer <Badge type="tip" text="Three views" />

The example exercises each built-in authoring option:

- Vanilla HTML, CSS, and JavaScript
- React TSX bundled by Deno
- Svelte components built by Vite running on Deno

Each provider discovers its source documents and mount declarations. Studio
resolves mounted cell, output, and value targets against the notebook's
symbolic graph.

[Run the NGA collection explorer](nga.md)

Use [Create your first view](../guide/getting-started.md) to apply the same
model to an existing notebook.
