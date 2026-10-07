import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "vite-plus/test";

interface SelectionOptions {
  readonly event?: string;
  readonly names?: readonly string[];
  readonly deferred?: Readonly<Record<string, DeferredRule>>;
  readonly deferredJson?: string;
}

interface DeferredRule {
  readonly filter: string | readonly string[];
  readonly escalate: string;
}

const selector = join(import.meta.dirname, "select.ts");

const select = async (
  mode: string,
  filters: Readonly<Record<string, string>>,
  {
    event = "pull_request",
    names = ["python_contracts", "main_browser"],
    deferred,
    deferredJson = deferred === undefined ? undefined : JSON.stringify(deferred),
  }: SelectionOptions = {},
) => {
  const directory = await mkdtemp(join(tmpdir(), "validation-selection-"));
  const output = join(directory, "output");
  try {
    const result = spawnSync(process.execPath, [selector], {
      encoding: "utf8",
      env: {
        ...process.env,
        GITHUB_OUTPUT: output,
        VALIDATION_MODE: mode,
        VALIDATION_EVENT: event,
        VALIDATION_FILTERS: JSON.stringify(names),
        DEFERRED_FILTERS: deferredJson,
        PATH_FILTERS_JSON: JSON.stringify(filters),
      },
    });
    const selected = existsSync(output) ? await readFile(output, "utf8") : "";
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

test("malformed deferred rules fail closed", async () => {
  for (const deferredJson of [
    "null",
    '{"platforms":null}',
    '{"platforms":{"filter":[],"escalate":"platform_sensitive"}}',
    '{"platforms":{"filter":["python_contracts",1],"escalate":"platform_sensitive"}}',
    '{"platforms":{"filter":"python_contracts","escalate":1}}',
    '{"Platforms":{"filter":"python_contracts","escalate":"platform_sensitive"}}',
  ]) {
    const result = await select(
      "changed",
      { python_contracts: "true", platform_sensitive: "true" },
      { names: [], deferredJson },
    );
    assert.notEqual(result.status, 0, deferredJson);
    assert.equal(result.selected, "", deferredJson);
  }
});
