import { describe, expect, it } from "vite-plus/test";

import type { DocumentationExampleFamily, DocumentationExampleView } from "../examples.ts";

import { selectDocumentationExamples } from "./example-selection.ts";

const view = (key: string): DocumentationExampleView => ({
  key,
  label: key,
  poster: "tall",
  technologies: [],
});

const families: readonly DocumentationExampleFamily[] = [
  {
    notebook: "examples/alpha.py",
    slug: "alpha",
    title: "Alpha",
    views: [view("overview"), view("paper")],
  },
  { notebook: "examples/beta.py", slug: "beta", title: "Beta", views: [view("story")] },
  {
    notebook: "examples/gamma.py",
    slug: "gamma",
    title: "Gamma",
    views: [view("monitor"), view("report")],
  },
];

describe("documentation example selection", () => {
  it("selects every notebook and view by default", () => {
    const selection = selectDocumentationExamples(families, []);

    expect(selection.complete).toBe(true);
    expect(selection.notebooks).toBe(3);
    expect(selection.views).toBe(5);
  });

  it("unions family, notebook, and view selectors", () => {
    const selection = selectDocumentationExamples(families, [
      "--",
      "--family",
      "alpha",
      "--notebook=beta",
      "--view",
      "gamma/monitor",
      "--view=gamma/monitor",
    ]);

    expect(selection.complete).toBe(false);
    expect(selection.notebooks).toBe(2);
    expect(selection.views).toBe(3);
    expect(
      selection.families.map(({ family, notebook, views }) => ({
        slug: family.slug,
        notebook,
        views: views.map((selected) => selected.key),
      })),
    ).toEqual([
      { slug: "alpha", notebook: true, views: ["overview", "paper"] },
      { slug: "beta", notebook: true, views: [] },
      { slug: "gamma", notebook: false, views: ["monitor"] },
    ]);
  });

  it.each([
    [["--family", "missing"], "Unknown documentation example family"],
    [["--view", "alpha/missing"], "Unknown documentation example view"],
    [["--view", "alpha"], "--view requires FAMILY/VIEW"],
    [["--notebook", "alpha/overview"], "--notebook requires a family slug"],
    [["--unknown"], "Unknown examples build option"],
  ])("rejects invalid selectors", (arguments_, message) => {
    expect(() => selectDocumentationExamples(families, arguments_)).toThrow(message);
  });
});
