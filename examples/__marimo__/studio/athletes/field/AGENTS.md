# Athlete Field view

This view presents the Rio 2016 athlete roster as an immersive briefing for a
live audience. Shower owns chapter navigation, keyboard controls, touch
gestures, progress, and the slide overview. Three.js renders one point for each
record in the projected `athlete_facts` table.

Keep the project on the `marimo-studio/vanilla` provider. `index.html` is the
entry document and owns structure and projection hosts. `style.css` owns the
visual system. `main.js` owns the point field and presentation behavior. Import
browser dependencies from exact HTTPS ESM URLs and keep the
`mo-value="athlete_facts"` host in the entry document so Studio can authorize
the projection.

The entry document loads the pinned UnoCSS runtime and Iconify web component.
Use UnoCSS for ordinary layout and spacing that stays readable in the markup,
and use Iconify for navigation icons. Keep `style.css` focused on the point
field, presentation modes, visual tokens, responsive composition, and motion.

The four chapters reuse the same points:

1. the full roster on a sphere
2. athletes gathered by sport
3. medalists pulled into the center
4. reported height, weight, and age mapped to three axes

The sports chapter mounts the notebook's `sport_control` cell. Observe
`athlete_summary.selection` to move the selected sport into the center, fade the
remaining clusters, and update the Three.js colors. Project the selected
athlete, delegation, and medalist counts directly from `athlete_summary`.
Project Games-wide participation, medal, and body-profile measures directly from
`games_summary`. Shower clones the active slide into its accessibility region.
Keep `sanitizeLiveRegion` registered after Shower starts so cloned slide content
cannot retain Studio projection-site identity or mount the filter twice.

Preserve deterministic layouts so the same athlete returns to the same place.
Keep captions factual and derive spatial layouts from the projected rows.
Maintain the flat black, chalk, and signal-blue system in `DESIGN.md`. Support
pointer inspection as an enhancement while keeping the chapter copy complete on
its own. Render WebGL on demand when reduced motion is active, with fresh frames
after layout transitions, resizes, pointer changes, and motion preference
changes. Keep continuous field rotation for the default motion preference.

Run Studio inspection and production build after source changes. Export the view
through the WASM runtime and check both a desktop viewport and a narrow mobile
viewport in a browser. Exercise arrow-key navigation, the visible controls,
sport selection, slide overview, fullscreen, hover details, and reduced motion.

## Visual direction

Keep the presentation calm and focused on the data. Use the current view CSS
as the visual baseline: restrained headings, readable labels, neutral surfaces,
fine borders, and color for selection or analytical meaning. Preserve the
view's distinct audience and interaction model. Check phone, tablet, desktop,
and short landscape layouts, including populated controls and long values.
