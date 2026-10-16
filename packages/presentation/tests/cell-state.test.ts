import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  cellDeliveryPhase,
  cellPhase,
  deliveryTimedOut,
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
    projectionPresent: true,
    hasCell: false,
    hasDiagnostic: false,
    timedOut: false,
  };

  assert.deepEqual(cellDeliveryPhase(pending), "waiting");
  assert.deepEqual(cellDeliveryPhase({ ...pending, timedOut: true }), "timed-out");
  assert.deepEqual(cellDeliveryPhase({ ...pending, hasDiagnostic: true }), "missing");
  assert.deepEqual(cellDeliveryPhase({ ...pending, hasCell: true }), "received");
});

test("a delivery timeout belongs to one projection cycle", () => {
  const timeout = { identity: "cell:v1:old" };

  assert.equal(deliveryTimedOut(true, "cell:v1:old", timeout), true);
  assert.equal(deliveryTimedOut(true, "cell:v1:new", timeout), false);
  assert.equal(deliveryTimedOut(false, "cell:v1:old", timeout), false);
});

test("terminal Marimo connections preserve their diagnostic", () => {
  const startup = runtimeConnectionDiagnostic({
    code: "KERNEL_STARTUP_ERROR",
    reason: "Failed to start kernel sandbox",
  });
  assert.equal(startup.code, "kernel-startup-error");
  assert.match(startup.message, /Failed to start kernel sandbox/);
  assert.ok(startup.hint.trim());

  const disconnected = runtimeConnectionDiagnostic({
    code: "KERNEL_DISCONNECTED",
    reason: "not authorized",
  });
  assert.equal(disconnected.code, "kernel-disconnected");
  assert.match(disconnected.message, /not authorized/);
  assert.ok(disconnected.hint.trim());
});
