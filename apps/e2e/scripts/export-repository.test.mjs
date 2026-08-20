import assert from "node:assert/strict";
import { access, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve, sep } from "node:path";
import test from "node:test";

import { withTemporaryExportRepository } from "./export-repository.mjs";

void test("static exports borrow a repository separate from the live server", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-e2e-repository-"));
  let repository = "";
  try {
    const result = await withTemporaryExportRepository(root, async (current) => {
      repository = current;
      assert.notEqual(current, resolve(root, "export-repository"));
      assert.equal(current.startsWith(`${root}${sep}`), true);
      await writeFile(resolve(current, "marker"), "ready", "utf8");
      return "complete";
    });

    assert.equal(result, "complete");
    await assert.rejects(access(repository), { code: "ENOENT" });
  } finally {
    await rm(root, { force: true, recursive: true });
  }
});

void test("static export repository cleanup preserves the primary failure", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-e2e-repository-"));
  let repository = "";
  try {
    await assert.rejects(
      withTemporaryExportRepository(root, async (current) => {
        repository = current;
        throw new Error("export failed");
      }),
      /export failed/,
    );
    await assert.rejects(access(repository), { code: "ENOENT" });
  } finally {
    await rm(root, { force: true, recursive: true });
  }
});
