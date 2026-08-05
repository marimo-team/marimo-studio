import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import {
  pageReadinessState,
  setRuntimeConnectionState,
  startReadiness,
  stopReadiness,
} from "../src/readiness.ts";
import { valueCellPhase } from "../src/runtime/value-cell-state.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
};

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

afterEach(stopReadiness);

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

test("a stale value opens a new idle batch while its snapshot remains visible", async () => {
  document.body.innerHTML = `<span mo-value="report" data-state="ready"></span>`;
  const source = document.querySelector<HTMLElement>("[mo-value]")!;
  let idleEvents = 0;
  document.addEventListener("marimo-studio:idle", () => idleEvents++);
  startReadiness(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();
  const initialEvents = idleEvents;

  source.dataset.state = "stale";
  await settleMutations();
  let resolved = false;
  const ready = globalThis.marimoStudio.ready().then(() => {
    resolved = true;
  });
  await Promise.resolve();
  assert.equal(resolved, false);
  assert.equal(idleEvents, initialEvents);
  assert.equal(document.documentElement.dataset.marimoStudioState, "ready");

  source.dataset.state = "ready";
  await ready;
  assert.equal(idleEvents, initialEvents + 1);
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
