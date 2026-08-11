import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { RuntimeCell } from "../src/runtime/runtime-cell.ts";

import { valueCellModel } from "../src/runtime/values/value-cell-model.ts";

test("an idle kernel value remains readable when a secondary client has stale source metadata", () => {
  const cell = {
    id: "cell-id",
    name: "_",
    config: { disabled: false },
    consoleOutputs: [],
    debuggerActive: false,
    status: "idle",
    lastRunStartTimestamp: 2,
    errored: false,
    edited: true,
    staleInputs: false,
    interrupted: false,
    output: null,
    runStartTimestamp: null,
    lastCodeRun: "old_name = 1",
    code: "current_name = 1",
  } as RuntimeCell;

  assert.deepEqual(valueCellModel(cell, true, false), {
    cellId: "cell-id",
    hasCell: true,
    phase: "ready",
    version: 2,
  });
});

test("an idle value waits while its kernel inputs are stale", () => {
  const cell = {
    id: "cell-id",
    name: "_",
    config: { disabled: false },
    consoleOutputs: [],
    debuggerActive: false,
    status: "idle",
    lastRunStartTimestamp: 2,
    errored: false,
    edited: false,
    staleInputs: true,
    interrupted: false,
    output: null,
    runStartTimestamp: null,
  } as RuntimeCell;

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
