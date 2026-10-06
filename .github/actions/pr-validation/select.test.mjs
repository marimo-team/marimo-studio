import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const selector = new URL("./select.mjs", import.meta.url);

const select = async (
  mode,
  filters,
  {
    event = "pull_request",
    names = ["python_contracts", "main_browser"],
    deferred = undefined,
  } = {},
) => {
  const directory = await mkdtemp(join(tmpdir(), "validation-selection-"));
  const output = join(directory, "output");
  try {
    const result = spawnSync(process.execPath, [fileURLToPath(selector)], {
      encoding: "utf8",
      env: {
        ...process.env,
        GITHUB_OUTPUT: output,
        VALIDATION_MODE: mode,
        VALIDATION_EVENT: event,
        VALIDATION_FILTERS: JSON.stringify(names),
        ...(deferred === undefined ? {} : { DEFERRED_FILTERS: JSON.stringify(deferred) }),
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

const platforms = { platforms: { filter: "python_contracts", escalate: "platform_sensitive" } };

test("a pull request defers platform contracts unless an escalation path changed", async () => {
  const options = { names: [], deferred: platforms };
  assert.equal(
    (await select("changed", { python_contracts: "true", platform_sensitive: "false" }, options))
      .selected,
    "platforms=false\n",
  );
  assert.equal(
    (await select("changed", { python_contracts: "true", platform_sensitive: "true" }, options))
      .selected,
    "platforms=true\n",
  );
  assert.equal(
    (await select("changed", { python_contracts: "false", platform_sensitive: "true" }, options))
      .selected,
    "platforms=false\n",
  );
});

test("a main push runs deferred contracts for its changed paths", async () => {
  const options = { event: "push", names: [], deferred: platforms };
  assert.equal(
    (await select("changed", { python_contracts: "true", platform_sensitive: "false" }, options))
      .selected,
    "platforms=true\n",
  );
  assert.equal(
    (await select("changed", { python_contracts: "false", platform_sensitive: "true" }, options))
      .selected,
    "platforms=false\n",
  );
});

test("exact-tree reuse still runs deferred contracts after merge", async () => {
  assert.equal(
    (
      await select(
        "reuse",
        { python_contracts: "true", platform_sensitive: "false" },
        { event: "push", deferred: platforms },
      )
    ).selected,
    "python_contracts=false\nmain_browser=false\nplatforms=true\n",
  );
});

test("full validation selects deferred contracts on a pull request", async () => {
  assert.equal(
    (await select("full", {}, { names: [], deferred: platforms })).selected,
    "platforms=true\n",
  );
});

test("deferred contracts cannot reuse a pull request output name", async () => {
  const result = await select(
    "changed",
    { python_contracts: "true", main_browser: "true", platform_sensitive: "true" },
    { deferred: { main_browser: platforms.platforms } },
  );
  assert.notEqual(result.status, 0);
  assert.equal(result.selected, "");
});

test("a deferred contract selects when any of its filters matched", async () => {
  const deferred = {
    platforms: {
      filter: ["python_contracts", "platform_control"],
      escalate: "platform_sensitive",
    },
  };
  const filters = {
    python_contracts: "false",
    platform_control: "true",
    platform_sensitive: "true",
  };
  assert.equal(
    (await select("changed", filters, { names: [], deferred })).selected,
    "platforms=true\n",
  );
  assert.equal(
    (await select("changed", filters, { event: "push", names: [], deferred })).selected,
    "platforms=true\n",
  );
});

test("a deferred contract fails closed when one of its filters is missing", async () => {
  const result = await select(
    "changed",
    { python_contracts: "true", platform_sensitive: "true" },
    {
      names: [],
      deferred: {
        platforms: {
          filter: ["python_contracts", "platform_control"],
          escalate: "platform_sensitive",
        },
      },
    },
  );
  assert.notEqual(result.status, 0);
  assert.equal(result.selected, "");
});
