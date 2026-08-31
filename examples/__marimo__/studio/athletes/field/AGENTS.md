# Athlete Field view

This view presents the Rio 2016 athlete roster as an immersive briefing for a
live audience. Shower owns chapter navigation, keyboard controls, touch
gestures, progress, and the slide overview. Three.js renders one point for each
record in the projected `athlete_facts` table.

Keep the project on the `marimo-studio/vanilla` provider. `index.html` is the
complete authored document. Import browser dependencies from exact HTTPS ESM
URLs and keep the `mo-value="athlete_facts"` host in the document so Studio can
authorize the projection.

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
its own.

Run Studio inspection and production build after source changes. Export the view
through the WASM runtime and check both a desktop viewport and a narrow mobile
viewport in a browser. Exercise arrow-key navigation, the visible controls,
sport selection, slide overview, fullscreen, hover details, and reduced motion.
