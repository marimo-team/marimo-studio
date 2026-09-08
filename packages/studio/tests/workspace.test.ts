import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { LayoutController } from "../src/features/workspace/controller.ts";
import {
  computeLayout,
  developLayout,
  equalizeLayout,
  layoutForMode,
  needsCompactLayout,
  parseLayout,
  splitSurface,
  sourceLayout,
  swapSurfaces,
  updateRatio,
  visibleSurfaces,
} from "../src/features/workspace/model.ts";
import { applyActiveMode, LayoutStorage } from "../src/features/workspace/storage.ts";

test("Develop gives Notebook and Preview equal full-height panes", () => {
  const bounds = {
    left: 0,
    top: 0,
    width: 1205,
    height: 805,
  };
  const layout = computeLayout(developLayout(), bounds);
  const notebook = layout.panes.get("notebook")!;
  assert.deepEqual([...layout.panes.keys()], ["notebook", "preview"]);
  const preview = layout.panes.get("preview")!;

  assert.equal(notebook.left, bounds.left);
  assert.equal(notebook.top, bounds.top);
  assert.equal(notebook.height, bounds.height);
  assert.equal(preview.top, bounds.top);
  assert.equal(preview.height, bounds.height);
  assert.equal(notebook.width, preview.width);
  assert.ok(preview.left > notebook.left + notebook.width);
});

test("task modes resolve to their surface layouts", () => {
  const source = sourceLayout();
  const workspace = developLayout();

  assert.deepEqual(visibleSurfaces(layoutForMode("develop", source, workspace)), [
    "notebook",
    "preview",
  ]);
  assert.deepEqual(visibleSurfaces(layoutForMode("notebook", source, workspace)), ["notebook"]);
  assert.deepEqual(visibleSurfaces(layoutForMode("preview", source, workspace)), ["preview"]);
  assert.deepEqual(visibleSurfaces(layoutForMode("source", source, workspace)), [
    "source",
    "preview",
  ]);
  assert.deepEqual(visibleSurfaces(layoutForMode("workspace", source, workspace)), [
    "notebook",
    "preview",
  ]);
});

test("compact mode follows the minimum size of the visible layout", () => {
  const tree = developLayout();

  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 800 }), false);
  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 604, height: 800 }), true);
  assert.equal(needsCompactLayout(tree, { left: 0, top: 0, width: 1200, height: 219 }), true);
});

test("nested ratios update and equalize independently", () => {
  const tree = splitSurface(developLayout(), "preview", "source", "above");
  const changed = updateRatio(updateRatio(tree, "notebook-preview", 0.6), "custom-1", 0.3);
  const equalized = equalizeLayout(changed);

  assert.equal(changed.type, "split");
  assert.equal(equalized.type, "split");
  assert.equal(equalized.second.type, "split");
  assert.deepEqual(changed.ratio, 0.6);
  assert.deepEqual(equalized.ratio, 0.5);
  assert.deepEqual(equalized.second.ratio, 0.5);
});

test("swapping panes exchanges their surfaces", () => {
  assert.deepEqual(visibleSurfaces(swapSurfaces(developLayout(), "notebook", "preview")), [
    "preview",
    "notebook",
  ]);
});

test("a pane can be placed on any side of its target", () => {
  const place = (placement: "left" | "right" | "above" | "below") => {
    const panes = computeLayout(splitSurface(developLayout(), "preview", "source", placement), {
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
  const saved = updateRatio(developLayout(), "notebook-preview", 0.6);
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

test("workspace storage round-trips valid state and recovers invalid data", () => {
  const storage = new LayoutStorage("studio-workspace");
  const state = {
    mode: "workspace" as const,
    source: sourceLayout(),
    workspace: developLayout(),
    compact: "preview" as const,
  };

  storage.write("dashboard", state);
  assert.deepEqual(storage.read("dashboard"), state);

  globalThis.localStorage.setItem(
    "studio-workspace:dashboard",
    JSON.stringify({
      schema: 1,
      mode: "notebook",
      source: sourceLayout(),
      workspace: developLayout(),
      compact: "source",
    }),
  );
  assert.deepEqual(storage.read("dashboard"), {
    mode: "notebook",
    source: sourceLayout(),
    workspace: developLayout(),
    compact: "notebook",
  });

  globalThis.localStorage.setItem("studio-workspace:dashboard", "invalid");
  assert.deepEqual(storage.read("dashboard"), {
    mode: "develop",
    source: sourceLayout(),
    workspace: developLayout(),
    compact: "notebook",
  });

  globalThis.localStorage.setItem(
    "studio-workspace:dashboard",
    JSON.stringify({
      schema: 99,
      mode: "source",
      source: sourceLayout(),
      workspace: developLayout(),
      compact: "source",
    }),
  );
  assert.deepEqual(storage.read("dashboard"), {
    mode: "develop",
    source: sourceLayout(),
    workspace: developLayout(),
    compact: "notebook",
  });
});

test("link navigation keeps the active mode and the target view split trees", () => {
  const source = updateRatio(sourceLayout(), "source-preview", 0.65);
  const workspace = updateRatio(developLayout(), "notebook-preview", 0.4);
  const target = {
    mode: "notebook" as const,
    source,
    workspace,
    compact: "notebook" as const,
  };

  assert.deepEqual(applyActiveMode(target, { mode: "workspace", compact: "preview" }), {
    mode: "workspace",
    source,
    workspace,
    compact: "preview",
  });
  assert.equal(
    applyActiveMode(target, { mode: "notebook", compact: "source" }).compact,
    "notebook",
  );
});

test("Source toggles beneath Notebook while Preview keeps its height and split width", () => {
  const controller = new LayoutController("source-toggle", "dashboard");
  const bounds = { left: 0, top: 0, width: 1205, height: 805 };
  controller.resize(updateRatio(controller.getSnapshot().tree, "notebook-preview", 0.6));
  const initial = controller.getSnapshot().tree;
  const preview = computeLayout(initial, bounds).panes.get("preview");
  controller.toggleSource();
  const opened = controller.getSnapshot();
  const panes = computeLayout(opened.tree, bounds).panes;
  assert.equal(opened.compact, "source");
  assert.deepEqual(panes.get("preview"), preview);
  assert.ok(panes.get("source")!.top > panes.get("notebook")!.top);
  controller.toggleSource();
  assert.deepEqual(controller.getSnapshot().tree, initial);
  assert.equal(controller.getSnapshot().compact, "notebook");
  controller.dispose();
});

test("Source can be opened from Preview and from a Source-only workspace", () => {
  const controller = new LayoutController("source-focus", "dashboard");
  controller.selectMode("preview");
  controller.toggleSource();
  assert.deepEqual(visibleSurfaces(controller.getSnapshot().tree), ["source", "preview"]);
  controller.toggleSource();
  assert.deepEqual(visibleSurfaces(controller.getSnapshot().tree), ["preview"]);
  controller.applyPaneAction({ tree: { type: "pane", id: "pane-source", surface: "source" } });
  controller.toggleSource();
  assert.deepEqual(visibleSurfaces(controller.getSnapshot().tree), ["notebook", "preview"]);
  controller.dispose();
});
