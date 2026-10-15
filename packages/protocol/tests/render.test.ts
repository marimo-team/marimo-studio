import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { renderSourceSchema } from "../src/projections.ts";
import { renderIndexSchema, renderRequestSchema, renderResultSchema } from "../src/render.ts";

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
};

test("render results name their main and preview files from the bundle", () => {
  assert.deepEqual(renderResultSchema.parse(result), result);
  assert.equal(renderResultSchema.safeParse({ ...result, main: "missing.pdf" }).success, false);
  assert.equal(renderResultSchema.safeParse({ ...result, preview: "../1.png" }).success, false);
  assert.equal(
    renderResultSchema.safeParse({
      ...result,
      files: [{ ...result.files[0], path: "/etc/passwd" }],
      main: "/etc/passwd",
      preview: null,
    }).success,
    false,
  );
});

test("a static render index keys results by state fingerprint, then render", () => {
  const index = renderIndexSchema.parse({
    schema: 1,
    states: { "state-a": { "report.md": result } },
  });

  assert.equal(index.states["state-a"]?.["report.md"]?.bundle, "a".repeat(64));
  assert.equal(
    renderIndexSchema.safeParse({ schema: 1, states: { "state-a": { "../report.md": result } } })
      .success,
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
  assert.equal(renderResultSchema.safeParse({ ...result, preview: "report.docx" }).success, false);
});

test("render bundle paths use forward slashes", () => {
  assert.equal(
    renderResultSchema.safeParse({
      ...result,
      files: [result.files[0], { ...result.files[1], path: "pages\\1.png" }],
      preview: "pages\\1.png",
    }).success,
    false,
  );
});
