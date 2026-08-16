import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { valueCellModel } from "../src/runtime/values/value-cell-model.ts";
import { runtimeCellFixture } from "./runtime-cell-fixture.ts";

test("an idle kernel value remains readable when a secondary client has stale source metadata", () => {
  const cell = runtimeCellFixture({
    lastRunStartTimestamp: 2,
    edited: true,
    lastCodeRun: "old_name = 1",
    code: "current_name = 1",
  });

  assert.deepEqual(valueCellModel(cell, true, false), {
    cellId: "cell-id",
    hasCell: true,
    phase: "ready",
    version: 2,
  });
});

test("an idle value waits while its kernel inputs are stale", () => {
  const cell = runtimeCellFixture({
    lastRunStartTimestamp: 2,
    staleInputs: true,
  });

  assert.deepEqual(valueCellModel(cell, true, false), {
    cellId: "cell-id",
    hasCell: true,
    phase: "stale",
    version: 2,
  });

  cell.staleInputs = false;
  assert.equal(valueCellModel(cell, true, false).phase, "ready");

  cell.staleInputs = true;
  cell.interrupted = true;
  assert.equal(valueCellModel(cell, true, false).phase, "ready");
});
