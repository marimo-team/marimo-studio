import { assertEquals } from "@std/assert";

import {
  retainUnmountedUIValues,
  type UIValueRegistry,
} from "../src/marimo-adapter/peer-controls.ts";

class Registry implements UIValueRegistry<string, unknown> {
  readonly values = new Map<string, unknown>();
  readonly delivered: string[] = [];

  has(objectId: string) {
    return this.values.has(objectId);
  }

  set(objectId: string, value: unknown) {
    this.values.set(objectId, value);
  }

  broadcastMessage(
    objectId: string,
    _message: unknown,
    _buffers: readonly DataView[],
  ) {
    if (this.has(objectId)) {
      this.delivered.push(objectId);
    }
  }
}

Deno.test("peer values survive until their control mounts", () => {
  const registry = new Registry();
  retainUnmountedUIValues(registry);

  registry.broadcastMessage(
    "slider",
    { type: "marimo-ui-value-update", value: 8 },
    [],
  );

  assertEquals(registry.values.get("slider"), 8);
  assertEquals(registry.delivered, ["slider"]);
});

Deno.test("ephemeral messages remain scoped to mounted controls", () => {
  const registry = new Registry();
  retainUnmountedUIValues(registry);

  registry.broadcastMessage("button", { type: "custom" }, []);

  assertEquals(registry.has("button"), false);
  assertEquals(registry.delivered, []);
});
