# HTML starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the single-document project
supplied by this starter.

## Project intent

Build a geospatial scrollytelling report for public readers. Import Observable
Plot as one pinned ESM dependency and use native `IntersectionObserver` for four
story steps. Follow the Seismic Broadsheet Atlas in `DESIGN.md`: concrete paper,
serif narrative, orange chapter signals, and a moss atlas plate. Use the
complete weekly event data and preserve source links to USGS records.

The entry document loads the pinned UnoCSS runtime and Iconify web component.
Use UnoCSS for ordinary page layout, spacing, and navigation icons. Keep inline
CSS for the atlas plate, scrollytelling states, chart transitions, tokens, and
responsive story behavior.

## Use the supplied Studio integration

`index.html` observes the complete `events` table and mounts the notebook's
`weekly_conclusion` cell. The four story filters remain local to the page.

`index.html` defines `observeMarimoValue` inside its module script. Use it when
page JavaScript consumes a notebook value or eager dataframe. Keep the
corresponding `mo-value` host in authored HTML so Studio can inspect and
authorize its selector.

```html
<span id="rows-data" hidden mo-value="rows"></span>
```

```js
const source = document.querySelector("#rows-data");
if (source) {
  const stop = observeMarimoValue(source, {
    onValue: (rows) => renderRows(rows),
    onError: (error) => renderError(error.message),
  });
  window.addEventListener("pagehide", stop, { once: true });
}
```

Eager dataframes arrive as a shared Flechette `Table`. Use
[https://github.com/uwdata/flechette](https://github.com/uwdata/flechette) as
the table API reference. Treat the table as immutable. Keep data columnar with
`getChild()`, `select()`, and `toColumns()`. Call `toArray()` when browser code
needs row objects.

## Add dependencies

Import browser-ready ESM modules at the top of the module script. Prefer a
versioned URL for maintained project source:

```js
import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";
```

Choose the URL form that matches the dependency source:

- Latest npm release for deliberate experiments:
  `import * as d3 from "https://cdn.jsdelivr.net/npm/d3/+esm";`
- Versioned npm package:
  `import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";`
- Concise statistical charts:
  `import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";`
- Tabular transformation:
  `import * as aq from "https://cdn.jsdelivr.net/npm/arquero@8/+esm";`
- Modular charting from an exported package subpath:
  `import * as echarts from "https://cdn.jsdelivr.net/npm/echarts@6/core/+esm";`
- CSV parsing from JSR through esm.sh:
  `import { parse as parseCsv } from "https://esm.sh/jsr/@std/csv";`

Remote modules require browser network access and a hosting content security
policy that allows the selected CDN. Keep all dependency origins explicit and
prefer versioned imports when the same source must rebuild consistently.

## Work within the HTML project

- Keep document structure, styles, and browser behavior in `index.html`.
- Keep projection hosts inside `#app-shell`.
- Inline project-owned CSS, JavaScript, images, and fonts with the document.
  External HTTP URLs and `data:` URLs remain available.
- Use browser APIs for focused interaction. Choose the React or Svelte starter
  when the page needs a component build and a multi-file application source.

Studio publishes this file directly after validating its HTML and projection
hosts. Treat the built document as the acceptance boundary for the page.

## Visual direction

Keep the presentation calm and focused on the data. Use the current view CSS
as the visual baseline: restrained headings, readable labels, neutral surfaces,
fine borders, and color for selection or analytical meaning. Preserve the
view's distinct audience and interaction model. Check phone, tablet, desktop,
and short landscape layouts, including populated controls and long values.
