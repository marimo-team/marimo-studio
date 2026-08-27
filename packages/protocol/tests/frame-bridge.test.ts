import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseFrameBridgeMessage } from "../src/frame-bridge.ts";

const identity = {
  lifecycleId: 3,
  revision: "revision-a",
  runtime: "wasm",
  sessionId: "s_preview",
  view: "dashboard",
};

interface CyclicBridgeProbe {
  generation: string;
  lifecycleId: number;
  revision: string;
  runtime: string;
  self?: CyclicBridgeProbe;
  sessionId: string;
  type: "marimo-studio:frame-control-update";
  update: { objectId: string; value: Record<string, never> };
  view: string;
}

test("frame bridge accepts bounded controls and rejects cyclic payloads", () => {
  const accepted = parseFrameBridgeMessage({
    type: "marimo-studio:frame-bridge-ready",
    generation: "generation-a",
    controls: [{ objectId: "cell-control", value: { selected: [1, 2] } }],
    ...identity,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(accepted)), {
    type: "marimo-studio:frame-bridge-ready",
    generation: "generation-a",
    controls: [{ objectId: "cell-control", value: { selected: [1, 2] } }],
    ...identity,
  });

  const cyclic: CyclicBridgeProbe = {
    type: "marimo-studio:frame-control-update",
    generation: "generation-a",
    update: { objectId: "cell-control", value: {} },
    ...identity,
  };
  cyclic.self = cyclic;
  assert.equal(parseFrameBridgeMessage(cyclic), undefined);

  assert.equal(
    parseFrameBridgeMessage({
      type: "marimo-studio:frame-control-update",
      generation: "generation-a",
      update: { objectId: "cell-control", value: "x".repeat(263_000) },
      ...identity,
    }),
    undefined,
  );
});
