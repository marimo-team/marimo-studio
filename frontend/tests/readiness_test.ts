import { assertEquals } from "@std/assert";

import { pageReadinessState } from "../src/readiness.ts";
import { valueCellPhase } from "../src/marimo-adapter/value-cell-state.ts";

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
  ...overrides,
});

Deno.test("readiness waits for pending hosts before publishing errors", () => {
  assertEquals(pageReadinessState("ready", ["error", "loading"]), "loading");
  assertEquals(pageReadinessState("ready", ["error", "ready"]), "error");
});

Deno.test("readiness settles when a host retains stale output", () => {
  assertEquals(pageReadinessState("ready", ["stale", "ready"]), "ready");
});

Deno.test("value cell phases follow the defining Marimo cell", () => {
  assertEquals(
    valueCellPhase(valueCell({
      hasCell: false,
      status: "missing",
      version: null,
    })),
    "error",
  );
  assertEquals(
    valueCellPhase(valueCell({
      disabled: true,
      version: null,
    })),
    "error",
  );
  assertEquals(
    valueCellPhase(valueCell({
      runtimeReady: false,
      hasCell: false,
      status: "missing",
      version: null,
    })),
    "loading",
  );
  assertEquals(
    valueCellPhase(valueCell({
      stale: true,
    })),
    "stale",
  );
  assertEquals(valueCellPhase(valueCell({ version: 2 })), "ready");
});
