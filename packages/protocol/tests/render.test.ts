import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { renderSourceSchema } from "../src/projections.ts";
import {
  indexedBundle,
  renderIndexSchema,
  renderRequestSchema,
  renderBundleSchema,
  type RenderRegion,
} from "../src/render.ts";

const result = {
  render: "report.md",
  bundle: "a".repeat(64),
  files: [
    { path: "report.docx", mediaType: "application/msword", sha256: "b".repeat(64), size: 10 },
    { path: "pages/1.png", mediaType: "image/png", sha256: "c".repeat(64), size: 20 },
  ],
  main: "report.docx",
  preview: "pages/1.png",
  warnings: [],
  absent: ["total"],
  regions: [
    {
      file: "pages/1.png",
      rect: { x: 0.1, y: 0.2, width: 0.5, height: 0.25 },
      reads: ["chart", "rows[0]"],
      page: null,
      start: null,
      end: null,
      source: { path: "report.md", line: 3, column: 1 },
      label: "Chart",
    },
  ],
};

test("render results name their main and preview files from the bundle", () => {
  assert.deepEqual(renderBundleSchema.parse(result), result);
  assert.equal(renderBundleSchema.safeParse({ ...result, main: "missing.pdf" }).success, false);
  assert.equal(renderBundleSchema.safeParse({ ...result, preview: "../1.png" }).success, false);
  assert.equal(
    renderBundleSchema.safeParse({
      ...result,
      files: [{ ...result.files[0], path: "/etc/passwd" }],
      main: "/etc/passwd",
      preview: null,
    }).success,
    false,
  );
});

test("a static render index stores each bundle once and names it from each state", () => {
  const { render, bundle, warnings, absent, ...content } = result;
  const states = {
    "state-a": { "report.md": { bundle, warnings, absent } },
    "state-b": { "report.md": { bundle, warnings: [], absent: [] } },
  };
  const index = renderIndexSchema.parse({ schema: 2, bundles: { [bundle]: content }, states });

  assert.deepEqual(indexedBundle(index, "state-a", "report.md"), result);
  assert.deepEqual(indexedBundle(index, "state-b", "report.md")?.absent, []);
  assert.equal(indexedBundle(index, "state-c", "report.md"), undefined);
  assert.equal(indexedBundle(index, "state-a", render.replace("report", "other")), undefined);
  assert.equal(renderIndexSchema.safeParse({ schema: 2, bundles: {}, states }).success, false);
  assert.equal(
    renderIndexSchema.safeParse({
      schema: 2,
      bundles: { [bundle]: content },
      states: { "state-a": { "../report.md": states["state-a"]["report.md"] } },
    }).success,
    false,
  );
});

test("render requests name the render, and browser runtimes add every read kind", () => {
  assert.equal(
    renderRequestSchema.safeParse({ revision: "r1", render: "report.md" }).success,
    true,
  );
  assert.equal(
    renderRequestSchema.safeParse({
      revision: "r1",
      render: "report.md",
      values: { total: 3 },
      outputs: { chart: { mimetype: "image/png", data: "data:image/png;base64,AA==" } },
      cells: {},
    }).success,
    true,
  );
  assert.equal(
    renderRequestSchema.safeParse({ revision: "r1", render: "report.md", values: {} }).success,
    false,
  );
});

test("a render source is a relative POSIX path to a project file", () => {
  for (const source of ["main.typ", "chapters/intro.typ"]) {
    assert.equal(renderSourceSchema.safeParse(source).success, true, source);
  }
  for (const source of ["", "../x", "/abs", "a//b", "./a", "a/", "chapters\\intro.typ"]) {
    assert.equal(renderSourceSchema.safeParse(source).success, false, source);
  }
});

test("a render result previews a file other than its main file", () => {
  assert.equal(renderBundleSchema.safeParse({ ...result, preview: "report.docx" }).success, false);
});

test("render bundle paths use forward slashes", () => {
  assert.equal(
    renderBundleSchema.safeParse({
      ...result,
      files: [result.files[0], { ...result.files[1], path: "pages\\1.png" }],
      preview: "pages\\1.png",
    }).success,
    false,
  );
});

test("a bundle's regions lie inside the surface of one of its files", () => {
  const [region] = result.regions;
  const accepts = (changes: Partial<RenderRegion>) =>
    renderBundleSchema.safeParse({ ...result, regions: [region, { ...region, ...changes }] })
      .success;

  assert.equal(accepts({ label: "Second" }), true);
  assert.equal(accepts({ file: "missing.png" }), false);
  assert.equal(accepts({ rect: { x: 0.6, y: 0, width: 0.5, height: 1 } }), false);
  assert.equal(accepts({ rect: { x: 0, y: 0, width: 0, height: 1 } }), false);
  assert.equal(accepts({ start: 2, end: 1 }), false);
  assert.equal(accepts({ page: 0 }), false);
});
