import { assertEquals } from "@std/assert";

import {
  cellDeliveryPhase,
  cellPhase,
  runtimeConnectionDiagnostic,
} from "../src/marimo-adapter/cell-state.ts";

const readyCell = {
  runtimeReady: true,
  hasCell: true,
  loading: false,
  disabled: false,
  hasOutput: true,
  failed: false,
  stale: false,
};

Deno.test("cell phases preserve retained output during recovery", () => {
  assertEquals(
    cellPhase({ ...readyCell, loading: true, failed: true }),
    "loading",
  );
  assertEquals(
    cellPhase({ ...readyCell, disabled: true, hasOutput: false }),
    "error",
  );
  assertEquals(cellPhase({ ...readyCell, disabled: true }), "ready");
  assertEquals(
    cellPhase({ ...readyCell, disabled: true, stale: true }),
    "ready",
  );
});

Deno.test("cell delivery bounds browser synchronization", () => {
  const pending = {
    runtimeReady: true,
    bindingPresent: true,
    hasCell: false,
    hasDiagnostic: false,
    timedOut: false,
  };

  assertEquals(cellDeliveryPhase(pending), "waiting");
  assertEquals(
    cellDeliveryPhase({ ...pending, timedOut: true }),
    "timed-out",
  );
  assertEquals(
    cellDeliveryPhase({ ...pending, hasDiagnostic: true }),
    "missing",
  );
  assertEquals(
    cellDeliveryPhase({ ...pending, hasCell: true }),
    "received",
  );
});

Deno.test("terminal Marimo connections preserve their diagnostic", () => {
  assertEquals(
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
  assertEquals(
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
