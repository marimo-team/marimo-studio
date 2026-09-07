import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const selector = new URL("./select.mjs", import.meta.url);

const select = async (mode, filters) => {
  const directory = await mkdtemp(join(tmpdir(), "validation-selection-"));
  const output = join(directory, "output");
  try {
    const result = spawnSync(process.execPath, [fileURLToPath(selector)], {
      encoding: "utf8",
      env: {
        ...process.env,
        GITHUB_OUTPUT: output,
        VALIDATION_MODE: mode,
        VALIDATION_FILTERS: JSON.stringify(["python_contracts", "main_browser"]),
        PATH_FILTERS_JSON: JSON.stringify(filters),
      },
    });
    const selected = await readFile(output, "utf8").catch((error) => {
      if (error.code === "ENOENT") return "";
      throw error;
    });
    return { selected, status: result.status };
  } finally {
    await rm(directory, { force: true, recursive: true });
  }
};

test("changed-file validation selects the affected contracts", async () => {
  assert.deepEqual(await select("changed", { python_contracts: "true", main_browser: "false" }), {
    status: 0,
    selected: "python_contracts=true\nmain_browser=false\n",
  });
});

test("full validation selects every contract when path classification was skipped", async () => {
  assert.deepEqual(await select("full", {}), {
    status: 0,
    selected: "python_contracts=true\nmain_browser=true\n",
  });
});

test("exact-tree reuse skips work covered by successful evidence", async () => {
  assert.deepEqual(await select("reuse", {}), {
    status: 0,
    selected: "python_contracts=false\nmain_browser=false\n",
  });
});

test("incomplete classification publishes no partial requirements", async () => {
  const result = await select("changed", { python_contracts: "true" });
  assert.notEqual(result.status, 0);
  assert.equal(result.selected, "");
});

test("unknown validation modes fail closed", async () => {
  const result = await select("unknown", {});
  assert.notEqual(result.status, 0);
  assert.equal(result.selected, "");
});
