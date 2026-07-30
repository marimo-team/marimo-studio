import { assertEquals } from "@std/assert";

import { cellPhase } from "../src/marimo-adapter/cell-state.ts";

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
