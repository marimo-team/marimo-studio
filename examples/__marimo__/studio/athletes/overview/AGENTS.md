# HTML starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the single-document project
supplied by this starter.

## Project intent

Build an entry-level Rio 2016 roster summary for readers learning Studio's
projection primitives. Use one self-contained HTML document with inline CSS and
JavaScript. Follow `DESIGN.md` and preserve the Nike Performance Index
composition. Keep the page compact and dependency-free. Place the native
`sport_control` cell beside scalar values and Marimo's rendered `top_sports`
dataframe.

## Use the supplied Studio integration

`index.html` mounts `sport_control`, renders `top_sports`, and projects four
paths from `athlete_summary`. Keep those selectors aligned with the notebook
when the report evolves.

This entry-level view uses declarative projection hosts and inline CSS. Keep
that direct contract intact. The sibling Explorer demonstrates programmatic
Arrow-table consumption and framework dependencies.

## Work within the HTML project

- Keep document structure, styles, and browser behavior in `index.html`.
- Keep projection hosts inside `#app-shell`.
- Inline project-owned CSS, JavaScript, images, and fonts with the document.
  External HTTP URLs and `data:` URLs remain available.
- Use browser APIs for focused interaction. Choose the React or Svelte starter
  when the page needs a component build and a multi-file application source.

Studio publishes this file directly after validating its HTML and projection
hosts. Treat the built document as the acceptance boundary for the page.
