# HTML starter instructions

Follow the Marimo Studio skill for notebook ownership, projection selection,
view lifecycle, and validation. This file covers the single-document project
supplied by this starter.

## Project intent

Build an entry-level Rio 2016 roster summary for readers learning Studio's
projection primitives. Use one self-contained HTML document with inline CSS and
JavaScript. Follow `DESIGN.md` and preserve the Nike Performance Index
composition. Use the pinned UnoCSS runtime for ordinary layout, spacing, and
responsive rules, and use Iconify for interface icons. Keep inline CSS for the
view's typography, palette, ranking chart, data table, state transitions, and
print-specific behavior. Place the native `sport_control` cell beside a compact
table populated from the projected `selected_roster` dataframe. Project
`top_sports` into the inline JavaScript chart.

## Use the supplied Studio integration

`index.html` mounts `sport_control`, projects `selected_roster` into its compact
table, and projects `top_sports` plus five paths from `athlete_summary`. Keep
those selectors aligned with the notebook when the report evolves.

This entry-level view uses declarative projection hosts, browser-native
JavaScript, provider-owned browser helpers, and focused inline CSS. Keep that
direct contract intact. The sibling Explorer adds a framework and browser query
engine for linked exploration.

## Work within the HTML project

- Keep document structure, styles, and browser behavior in `index.html`.
- Keep projection hosts inside `#app-shell`.
- Inline project-owned CSS, JavaScript, images, and fonts with the document.
  External HTTP URLs and `data:` URLs remain available.
- Use browser APIs for focused interaction. Choose the React or Svelte starter
  when the page needs a component build and a multi-file application source.

Studio publishes this file directly after validating its HTML and projection
hosts. Treat the built document as the acceptance boundary for the page.
