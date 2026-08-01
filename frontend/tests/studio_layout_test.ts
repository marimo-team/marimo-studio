import { assertEquals } from "@std/assert";

import {
  computeLayout,
  defaultLayout,
  equalizeLayout,
  needsCompactLayout,
  newViewLayout,
  parseLayout,
  splitSurface,
  swapSurfaces,
  updateRatio,
  visibleSurfaces,
} from "../src/studio/layout.ts";

Deno.test("the default workspace splits notebook and preview evenly", () => {
  const layout = computeLayout(defaultLayout(), {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  });

  assertEquals(layout.panes.get("notebook"), {
    left: 0,
    top: 0,
    width: 600,
    height: 805,
  });
  assertEquals(layout.panes.get("preview"), {
    left: 605,
    top: 0,
    width: 600,
    height: 805,
  });
  assertEquals(layout.panes.has("source"), false);
});

Deno.test("a new view opens source above preview beside the notebook", () => {
  const layout = computeLayout(newViewLayout(), {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  });

  assertEquals(layout.panes.get("notebook"), {
    left: 0,
    top: 0,
    width: 600,
    height: 805,
  });
  assertEquals(layout.panes.get("source"), {
    left: 605,
    top: 0,
    width: 600,
    height: 400,
  });
  assertEquals(layout.panes.get("preview"), {
    left: 605,
    top: 405,
    width: 600,
    height: 400,
  });
});

Deno.test("nested ratios update and equalize independently", () => {
  const tree = splitSurface(defaultLayout(), "preview", "source", "below");
  const changed = updateRatio(
    updateRatio(tree, "notebook-preview", 0.6),
    "custom-1",
    0.3,
  );
  const equalized = equalizeLayout(changed);

  assertEquals((changed as { ratio: number }).ratio, 0.6);
  assertEquals((equalized as { ratio: number }).ratio, 0.5);
  assertEquals(
    (equalized as { second: { ratio: number } }).second.ratio,
    0.5,
  );
});

Deno.test("pane operations keep each surface unique", () => {
  const restored = splitSurface(
    defaultLayout(),
    "preview",
    "source",
    "below",
  );

  assertEquals(visibleSurfaces(defaultLayout()), ["notebook", "preview"]);
  assertEquals(visibleSurfaces(restored).sort(), [
    "notebook",
    "preview",
    "source",
  ]);
  assertEquals(
    computeLayout(restored, { left: 0, top: 0, width: 1000, height: 805 })
      .dividers.find((divider) => divider.axis === "y")?.ratio,
    0.5,
  );
  assertEquals(
    visibleSurfaces(swapSurfaces(defaultLayout(), "notebook", "preview")),
    ["preview", "notebook"],
  );
});

Deno.test("a pane can be placed on any side of its target", () => {
  const place = (placement: "left" | "right" | "above" | "below") => {
    const panes = computeLayout(
      splitSurface(defaultLayout(), "preview", "source", placement),
      { left: 0, top: 0, width: 1205, height: 805 },
    ).panes;
    return {
      source: panes.get("source")!,
      preview: panes.get("preview")!,
    };
  };

  const left = place("left");
  assertEquals(left.source.left < left.preview.left, true);
  assertEquals(left.source.top, left.preview.top);

  const right = place("right");
  assertEquals(right.source.left > right.preview.left, true);
  assertEquals(right.source.top, right.preview.top);

  const above = place("above");
  assertEquals(above.source.top < above.preview.top, true);
  assertEquals(above.source.left, above.preview.left);

  const below = place("below");
  assertEquals(below.source.top > below.preview.top, true);
  assertEquals(below.source.left, below.preview.left);
});

Deno.test("saved layouts validate shape, ratios, and unique surfaces", () => {
  const serialized = JSON.stringify(
    updateRatio(defaultLayout(), "notebook-preview", 0.6),
  );

  assertEquals(
    parseLayout(serialized),
    updateRatio(defaultLayout(), "notebook-preview", 0.6),
  );
  assertEquals(
    parseLayout(
      JSON.stringify({
        type: "split",
        id: "duplicate",
        axis: "x",
        ratio: 0.5,
        first: { type: "pane", surface: "preview" },
        second: { type: "pane", surface: "preview" },
      }),
    ),
    null,
  );
  assertEquals(
    parseLayout(
      JSON.stringify({
        type: "split",
        id: "same-split",
        axis: "x",
        ratio: 0.5,
        first: { type: "pane", surface: "notebook" },
        second: {
          type: "split",
          id: "same-split",
          axis: "y",
          ratio: 0.5,
          first: { type: "pane", surface: "source" },
          second: { type: "pane", surface: "preview" },
        },
      }),
    ),
    null,
  );
});

Deno.test("compact projection follows the tree minimum size", () => {
  const tree = defaultLayout();

  assertEquals(
    needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 800 }),
    false,
  );
  assertEquals(
    needsCompactLayout(tree, { left: 0, top: 0, width: 500, height: 800 }),
    true,
  );
});
