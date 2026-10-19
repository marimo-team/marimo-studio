import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { projectCell } from "../src/runtime/cells/cell-projection.ts";
import { runtimeCellFixture } from "./runtime-cell-fixture.ts";

const project = (cell: ReturnType<typeof runtimeCellFixture>) =>
  projectCell({
    alias: "summary",
    projectionPresent: true,
    cell,
    deliveryTimedOut: false,
    runtimeReady: true,
    showCellLogs: false,
  });

const output = {
  channel: "output",
  mimetype: "text/markdown",
  data: "hello",
  timestamp: 1,
} as const;

test("an idle cell output stays ready when a secondary client has stale source metadata", () => {
  // marimo normalizes `mo.md("hello")` to a triple-quoted string on save, so a
  // reconnected session reports source that differs from the code the kernel ran.
  const cell = runtimeCellFixture({
    lastRunStartTimestamp: 2,
    edited: true,
    lastCodeRun: 'mo.md("hello")',
    code: 'mo.md("""\n    hello\n    """)',
    output,
  });

  const projection = project(cell);
  assert.equal(projection.state, "ready");
  assert.equal(projection.stale, false);
});

test("an idle cell output is stale while its kernel inputs are stale", () => {
  const cell = runtimeCellFixture({ lastRunStartTimestamp: 2, staleInputs: true, output });

  assert.equal(project(cell).state, "stale");
});
