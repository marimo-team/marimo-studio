import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  type EmbeddedControlRegistry,
  retainUnmountedControlValues,
} from "../src/embedded-control-state.ts";

type ControlValue = Parameters<EmbeddedControlRegistry<string>["set"]>[1];
type ControlMessage = Parameters<EmbeddedControlRegistry<string>["broadcastMessage"]>[1];

class Registry implements EmbeddedControlRegistry<string> {
  readonly values = new Map<string, ControlValue>();
  readonly delivered: string[] = [];

  has(objectId: string) {
    return this.values.has(objectId);
  }

  set(objectId: string, value: ControlValue) {
    this.values.set(objectId, value);
  }

  broadcastMessage(objectId: string, _message: ControlMessage, _buffers: readonly DataView[]) {
    if (this.has(objectId)) {
      this.delivered.push(objectId);
    }
  }
}

test("peer values survive until their control mounts", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);

  registry.broadcastMessage("slider", { type: "marimo-ui-value-update", value: 8 }, []);

  assert.deepEqual(registry.values.get("slider"), 8);
  assert.deepEqual(registry.delivered, ["slider"]);
});

test("ephemeral messages remain scoped to mounted controls", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);

  registry.broadcastMessage("button", { type: "custom" }, []);
  registry.broadcastMessage("slider", { type: "marimo-ui-value-update" }, []);

  assert.deepEqual(registry.has("button"), false);
  assert.deepEqual(registry.has("slider"), false);
  assert.deepEqual(registry.delivered, []);
});
