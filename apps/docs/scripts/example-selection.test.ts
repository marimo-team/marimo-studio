import { describe, expect, it } from "vite-plus/test";

import { documentationExampleFamilies } from "../examples.ts";
import { selectDocumentationExamples } from "./example-selection.ts";

describe("documentation example selection", () => {
  it("selects every notebook and view by default", () => {
    const selection = selectDocumentationExamples(documentationExampleFamilies, []);

    expect(selection.complete).toBe(true);
    expect(selection.notebooks).toBe(4);
    expect(selection.views).toBe(12);
  });

  it("unions family, notebook, and view selectors", () => {
    const selection = selectDocumentationExamples(documentationExampleFamilies, [
      "--",
      "--family",
      "athletes",
      "--notebook=earthquakes",
      "--view",
      "occupancy/monitor",
      "--view=occupancy/monitor",
    ]);

    expect(selection.complete).toBe(false);
    expect(selection.notebooks).toBe(2);
    expect(selection.views).toBe(4);
    expect(
      selection.families.map(({ family, notebook, views }) => ({
        slug: family.slug,
        notebook,
        views: views.map((view) => view.key),
      })),
    ).toEqual([
      {
        slug: "athletes",
        notebook: true,
        views: ["overview", "explorer", "field"],
      },
      { slug: "earthquakes", notebook: true, views: [] },
      { slug: "occupancy", notebook: false, views: ["monitor"] },
    ]);
  });

  it.each([
    [["--family", "missing"], "Unknown documentation example family"],
    [["--view", "athletes/missing"], "Unknown documentation example view"],
    [["--view", "athletes"], "--view requires FAMILY/VIEW"],
    [["--notebook", "athletes/overview"], "--notebook requires a family slug"],
    [["--unknown"], "Unknown examples build option"],
  ])("rejects invalid selectors", (arguments_, message) => {
    expect(() => selectDocumentationExamples(documentationExampleFamilies, arguments_)).toThrow(
      message,
    );
  });
});
