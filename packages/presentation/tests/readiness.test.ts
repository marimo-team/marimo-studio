import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { pageReadinessState } from "../src/readiness.ts";
import { valueCellPhase } from "../src/runtime/value-cell-state.ts";

const valueCell = (
  overrides: Partial<Parameters<typeof valueCellPhase>[0]> = {},
): Parameters<typeof valueCellPhase>[0] => ({
  runtimeReady: true,
  hasCell: true,
  disabled: false,
  status: "idle",
  version: 1,
  errored: false,
  stale: false,
  deliveryTimedOut: false,
  ...overrides,
});

test("page readiness accounts for pending and retained hosts", () => {
  assert.deepEqual(pageReadinessState("ready", ["error", "loading"]), "loading");
  assert.deepEqual(pageReadinessState("ready", ["error", "ready"]), "error");
  assert.deepEqual(pageReadinessState("ready", ["stale", "ready"]), "ready");
  assert.deepEqual(pageReadinessState("ready", ["ready"], "loading"), "loading");
  assert.deepEqual(pageReadinessState("ready", ["ready"], "error"), "error");
});

test("value cell phases follow the defining Marimo cell", () => {
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        hasCell: false,
        status: "missing",
        version: null,
      }),
    ),
    "loading",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        disabled: true,
        version: null,
      }),
    ),
    "error",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        runtimeReady: false,
        hasCell: false,
        status: "missing",
        version: null,
      }),
    ),
    "loading",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        hasCell: false,
        status: "missing",
        version: null,
        deliveryTimedOut: true,
      }),
    ),
    "error",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        stale: true,
      }),
    ),
    "stale",
  );
  assert.deepEqual(valueCellPhase(valueCell({ version: 2 })), "ready");
});
