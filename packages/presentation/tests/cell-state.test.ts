import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  cellDeliveryPhase,
  cellPhase,
  runtimeConnectionDiagnostic,
} from "../src/runtime/cell-state.ts";

const readyCell = {
  runtimeReady: true,
  hasCell: true,
  loading: false,
  disabled: false,
  hasOutput: true,
  failed: false,
  stale: false,
};

test("cell phases preserve retained output during recovery", () => {
  assert.deepEqual(cellPhase({ ...readyCell, loading: true, failed: true }), "loading");
  assert.deepEqual(cellPhase({ ...readyCell, disabled: true, hasOutput: false }), "error");
  assert.deepEqual(cellPhase({ ...readyCell, disabled: true }), "ready");
  assert.deepEqual(cellPhase({ ...readyCell, disabled: true, stale: true }), "ready");
});

test("cell delivery bounds browser synchronization", () => {
  const pending = {
    runtimeReady: true,
    bindingPresent: true,
    hasCell: false,
    hasDiagnostic: false,
    timedOut: false,
  };

  assert.deepEqual(cellDeliveryPhase(pending), "waiting");
  assert.deepEqual(cellDeliveryPhase({ ...pending, timedOut: true }), "timed-out");
  assert.deepEqual(cellDeliveryPhase({ ...pending, hasDiagnostic: true }), "missing");
  assert.deepEqual(cellDeliveryPhase({ ...pending, hasCell: true }), "received");
});

test("terminal Marimo connections preserve their diagnostic", () => {
  assert.deepEqual(
    runtimeConnectionDiagnostic({
      code: "KERNEL_STARTUP_ERROR",
      reason: "Failed to start kernel sandbox",
    }),
    {
      code: "kernel-startup-error",
      message: "Marimo connection closed: Failed to start kernel sandbox",
      hint: "Fix the notebook startup failure in Marimo, then reload the view.",
    },
  );
  assert.deepEqual(
    runtimeConnectionDiagnostic({
      code: "KERNEL_DISCONNECTED",
      reason: "not authorized",
    }),
    {
      code: "kernel-disconnected",
      message: "Marimo connection closed: not authorized",
      hint: "Reload the view after the Marimo server is available.",
    },
  );
});
