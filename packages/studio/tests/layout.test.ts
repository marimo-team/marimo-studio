import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  codeLayout,
  computeLayout,
  defaultWorkspaceLayout,
  equalizeLayout,
  layoutForMode,
  needsCompactLayout,
  newViewLayout,
  parseLayout,
  splitSurface,
  swapSurfaces,
  updateRatio,
  visibleSurfaces,
} from "../src/layout/model.ts";
import { applyActiveMode, LayoutStorage } from "../src/layout/storage.ts";

test("the custom workspace splits notebook and preview evenly", () => {
  const bounds = {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  };
  const layout = computeLayout(defaultWorkspaceLayout(), bounds);
  const notebook = layout.panes.get("notebook")!;
  const preview = layout.panes.get("preview")!;

  assert.equal(notebook.left, bounds.left);
  assert.equal(notebook.top, bounds.top);
  assert.equal(notebook.width, preview.width);
  assert.equal(notebook.height, bounds.height);
  assert.equal(preview.top, bounds.top);
  assert.equal(preview.height, bounds.height);
  assert.ok(preview.left > notebook.left + notebook.width);
  assert.deepEqual(layout.panes.has("source"), false);
});

test("task modes resolve to their surface layouts", () => {
  const code = codeLayout();
  const workspace = defaultWorkspaceLayout();

  assert.deepEqual(visibleSurfaces(layoutForMode("split", code, workspace)), [
    "notebook",
    "preview",
  ]);
  assert.deepEqual(visibleSurfaces(layoutForMode("notebook", code, workspace)), ["notebook"]);
  assert.deepEqual(visibleSurfaces(layoutForMode("preview", code, workspace)), ["preview"]);
  assert.deepEqual(visibleSurfaces(layoutForMode("code", code, workspace)), ["source", "preview"]);
  assert.deepEqual(visibleSurfaces(layoutForMode("workspace", code, workspace)), [
    "notebook",
    "preview",
  ]);
});

test("a new view opens source above preview beside the notebook", () => {
  const bounds = {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  };
  const layout = computeLayout(newViewLayout(), bounds);
  const notebook = layout.panes.get("notebook")!;
  const source = layout.panes.get("source")!;
  const preview = layout.panes.get("preview")!;

  assert.equal(notebook.left, bounds.left);
  assert.equal(notebook.height, bounds.height);
  assert.equal(source.left, preview.left);
  assert.ok(source.left > notebook.left + notebook.width);
  assert.equal(source.width, preview.width);
  assert.equal(source.height, preview.height);
  assert.equal(source.top, bounds.top);
  assert.ok(preview.top > source.top + source.height);
});

test("compact mode follows the minimum size of the visible layout", () => {
  const tree = newViewLayout();

  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 800 }), false);
  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 604, height: 800 }), true);
  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 444 }), true);
});

test("nested ratios update and equalize independently", () => {
  const tree = splitSurface(defaultWorkspaceLayout(), "preview", "source", "below");
  const changed = updateRatio(updateRatio(tree, "notebook-preview", 0.6), "custom-1", 0.3);
  const equalized = equalizeLayout(changed);

  assert.deepEqual((changed as { ratio: number }).ratio, 0.6);
  assert.deepEqual((equalized as { ratio: number }).ratio, 0.5);
  assert.deepEqual((equalized as { second: { ratio: number } }).second.ratio, 0.5);
});

test("pane operations keep each surface unique", () => {
  const restored = splitSurface(defaultWorkspaceLayout(), "preview", "source", "below");

  assert.deepEqual(visibleSurfaces(defaultWorkspaceLayout()), ["notebook", "preview"]);
  assert.deepEqual(visibleSurfaces(restored).sort(), ["notebook", "preview", "source"]);
  assert.deepEqual(
    computeLayout(restored, { left: 0, top: 0, width: 1000, height: 805 }).dividers.find(
      (divider) => divider.axis === "y",
    )?.ratio,
    0.5,
  );
  assert.deepEqual(visibleSurfaces(swapSurfaces(defaultWorkspaceLayout(), "notebook", "preview")), [
    "preview",
    "notebook",
  ]);
});

test("a pane can be placed on any side of its target", () => {
  const place = (placement: "left" | "right" | "above" | "below") => {
    const panes = computeLayout(
      splitSurface(defaultWorkspaceLayout(), "preview", "source", placement),
      {
        left: 0,
        top: 0,
        width: 1205,
        height: 805,
      },
    ).panes;
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
  const saved = updateRatio(defaultWorkspaceLayout(), "notebook-preview", 0.6);
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
      mode: "workspace" as const,
      code: codeLayout(),
      workspace: newViewLayout(),
      compact: "preview" as const,
    };

    storage.write("dashboard", state);
    assert.deepEqual(storage.read("dashboard"), state);

    values.set(
      "studio-layout:dashboard",
      JSON.stringify({
        schema: 1,
        mode: "notebook",
        code: codeLayout(),
        workspace: defaultWorkspaceLayout(),
        compact: "source",
      }),
    );
    assert.deepEqual(storage.read("dashboard"), {
      mode: "notebook",
      code: codeLayout(),
      workspace: defaultWorkspaceLayout(),
      compact: "notebook",
    });

    values.set("studio-layout:dashboard", "invalid");
    assert.deepEqual(storage.read("dashboard"), {
      mode: "split",
      code: codeLayout(),
      workspace: defaultWorkspaceLayout(),
      compact: "notebook",
    });
  } finally {
    if (previous) {
      Object.defineProperty(globalThis, "localStorage", previous);
    } else {
      Reflect.deleteProperty(globalThis, "localStorage");
    }
  }
});

test("link navigation keeps the active mode and the target view split trees", () => {
  const code = updateRatio(codeLayout(), "source-preview", 0.65);
  const workspace = updateRatio(newViewLayout(), "notebook-authoring", 0.4);
  const target = {
    mode: "notebook" as const,
    code,
    workspace,
    compact: "notebook" as const,
  };

  assert.deepEqual(applyActiveMode(target, { mode: "workspace", compact: "preview" }), {
    mode: "workspace",
    code,
    workspace,
    compact: "preview",
  });
  assert.equal(
    applyActiveMode(target, { mode: "notebook", compact: "source" }).compact,
    "notebook",
  );
});
