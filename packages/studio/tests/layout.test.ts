import assert from "node:assert/strict";
import { test } from "vite-plus/test";

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
} from "../src/layout/model.ts";
import { LayoutStorage } from "../src/layout/storage.ts";

test("the default workspace splits notebook and preview evenly", () => {
  const layout = computeLayout(defaultLayout(), {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  });

  assert.deepEqual(layout.panes.get("notebook"), {
    left: 0,
    top: 0,
    width: 600,
    height: 805,
  });
  assert.deepEqual(layout.panes.get("preview"), {
    left: 605,
    top: 0,
    width: 600,
    height: 805,
  });
  assert.deepEqual(layout.panes.has("source"), false);
});

test("a new view opens source above preview beside the notebook", () => {
  const layout = computeLayout(newViewLayout(), {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  });

  assert.deepEqual(layout.panes.get("notebook"), {
    left: 0,
    top: 0,
    width: 600,
    height: 805,
  });
  assert.deepEqual(layout.panes.get("source"), {
    left: 605,
    top: 0,
    width: 600,
    height: 400,
  });
  assert.deepEqual(layout.panes.get("preview"), {
    left: 605,
    top: 405,
    width: 600,
    height: 400,
  });
});

test("compact mode follows the minimum size of the visible layout", () => {
  const tree = newViewLayout();

  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 800 }), false);
  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 604, height: 800 }), true);
  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 444 }), true);
});

test("nested ratios update and equalize independently", () => {
  const tree = splitSurface(defaultLayout(), "preview", "source", "below");
  const changed = updateRatio(updateRatio(tree, "notebook-preview", 0.6), "custom-1", 0.3);
  const equalized = equalizeLayout(changed);

  assert.deepEqual((changed as { ratio: number }).ratio, 0.6);
  assert.deepEqual((equalized as { ratio: number }).ratio, 0.5);
  assert.deepEqual((equalized as { second: { ratio: number } }).second.ratio, 0.5);
});

test("pane operations keep each surface unique", () => {
  const restored = splitSurface(defaultLayout(), "preview", "source", "below");

  assert.deepEqual(visibleSurfaces(defaultLayout()), ["notebook", "preview"]);
  assert.deepEqual(visibleSurfaces(restored).sort(), ["notebook", "preview", "source"]);
  assert.deepEqual(
    computeLayout(restored, { left: 0, top: 0, width: 1000, height: 805 }).dividers.find(
      (divider) => divider.axis === "y",
    )?.ratio,
    0.5,
  );
  assert.deepEqual(visibleSurfaces(swapSurfaces(defaultLayout(), "notebook", "preview")), [
    "preview",
    "notebook",
  ]);
});

test("a pane can be placed on any side of its target", () => {
  const place = (placement: "left" | "right" | "above" | "below") => {
    const panes = computeLayout(splitSurface(defaultLayout(), "preview", "source", placement), {
      left: 0,
      top: 0,
      width: 1205,
      height: 805,
    }).panes;
    return {
      source: panes.get("source")!,
      preview: panes.get("preview")!,
    };
  };

  const left = place("left");
  assert.deepEqual(left.source.left < left.preview.left, true);
  assert.deepEqual(left.source.top, left.preview.top);

  const right = place("right");
  assert.deepEqual(right.source.left > right.preview.left, true);
  assert.deepEqual(right.source.top, right.preview.top);

  const above = place("above");
  assert.deepEqual(above.source.top < above.preview.top, true);
  assert.deepEqual(above.source.left, above.preview.left);

  const below = place("below");
  assert.deepEqual(below.source.top > below.preview.top, true);
  assert.deepEqual(below.source.left, below.preview.left);
});

test("saved layouts validate shape, ratios, and unique surfaces", () => {
  const saved = updateRatio(defaultLayout(), "notebook-preview", 0.6);
  const serialized = JSON.stringify(saved);

  assert.deepEqual(parseLayout(serialized), saved);
  assert.deepEqual(
    parseLayout(
      JSON.stringify({
        type: "split",
        id: "duplicate",
        axis: "x",
        ratio: 0.5,
        first: { type: "pane", id: "pane-preview", surface: "preview" },
        second: { type: "pane", id: "pane-preview", surface: "preview" },
      }),
    ),
    null,
  );
  assert.deepEqual(
    parseLayout(
      JSON.stringify({
        type: "split",
        id: "same-split",
        axis: "x",
        ratio: 0.5,
        first: { type: "pane", id: "pane-notebook", surface: "notebook" },
        second: {
          type: "split",
          id: "same-split",
          axis: "y",
          ratio: 0.5,
          first: { type: "pane", id: "pane-source", surface: "source" },
          second: { type: "pane", id: "pane-preview", surface: "preview" },
        },
      }),
    ),
    null,
  );
  assert.deepEqual(parseLayout(JSON.stringify({ ...saved, ratio: 1.2 })), null);
  assert.deepEqual(parseLayout("invalid"), null);
});

test("layout storage round-trips valid state and recovers invalid data", () => {
  const values = new Map<string, string>();
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    },
  });
  try {
    const storage = new LayoutStorage("studio-layout");
    const state = {
      tree: newViewLayout(),
      focused: "source" as const,
      compact: "preview" as const,
    };

    storage.write("dashboard", state);
    assert.deepEqual(storage.read("dashboard"), state);

    values.set(
      "studio-layout:dashboard",
      JSON.stringify({
        schema: 1,
        tree: defaultLayout(),
        focused: "source",
        compact: "source",
      }),
    );
    assert.deepEqual(storage.read("dashboard"), {
      tree: defaultLayout(),
      focused: null,
      compact: "notebook",
    });

    values.set("studio-layout:dashboard", "invalid");
    assert.deepEqual(storage.read("dashboard").tree, defaultLayout());
  } finally {
    if (previous) {
      Object.defineProperty(globalThis, "localStorage", previous);
    } else {
      Reflect.deleteProperty(globalThis, "localStorage");
    }
  }
});
