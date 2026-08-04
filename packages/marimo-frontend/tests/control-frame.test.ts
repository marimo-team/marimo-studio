import { describe, expect, test, vi } from "vite-plus/test";

import { connectControlEndpoint, type ReadyEvents } from "../src/control-endpoint.ts";

interface RegistryEntry {
  value: unknown;
}

class FakeRegistry {
  readonly entries = new Map<string, RegistryEntry>();
  readonly messages: Array<{ objectId: string; message: unknown }> = [];

  has(objectId: string): boolean {
    return this.entries.has(objectId);
  }

  lookupValue(objectId: string): unknown {
    return this.entries.get(objectId)?.value;
  }

  set(objectId: string, value: unknown): void {
    this.entries.set(objectId, { value });
  }

  registerInstance(objectId: string, instance: HTMLElement): void {
    if (!this.entries.has(objectId)) {
      this.set(objectId, (instance as HTMLElement & { value?: unknown }).value);
    }
  }

  broadcastMessage(objectId: string, message: unknown): void {
    this.messages.push({ objectId, message });
  }
}

class ReadyEvent extends Event {
  constructor(readonly objectId: string) {
    super("ready");
  }
}

const readyEvents: ReadyEvents = {
  type: "ready",
  objectId: (event) => (event instanceof ReadyEvent ? event.objectId : undefined),
};

describe("Marimo control frames", () => {
  test("retains an update before the target control mounts", () => {
    const registry = new FakeRegistry();
    const send = vi.fn(async () => null);
    const endpoint = connectControlEndpoint(new EventTarget(), registry, readyEvents, send);

    void endpoint.apply([{ objectId: "slider-0", value: 4 }]);

    expect(registry.entries.get("slider-0")?.value).toBe(4);
    expect(registry.messages).toEqual([
      {
        objectId: "slider-0",
        message: { type: "marimo-ui-value-update", value: 4 },
      },
    ]);
    expect(send).toHaveBeenCalledWith({ objectIds: ["slider-0"], values: [4] });
  });

  test("publishes a native control when it mounts after subscription", () => {
    const registry = new FakeRegistry();
    const endpoint = connectControlEndpoint(
      new EventTarget(),
      registry,
      readyEvents,
      async () => null,
    );
    const updates: unknown[] = [];
    endpoint.subscribe((update) => updates.push(update));

    registry.registerInstance("slider-0", { value: 7 } as HTMLElement & { value: number });

    expect(updates).toEqual([{ objectId: "slider-0", value: 7 }]);
  });

  test("applies a snapshot with one kernel request", async () => {
    const registry = new FakeRegistry();
    registry.set("first-0", 1);
    registry.set("second-0", 2);
    const send = vi.fn(async () => null);
    const endpoint = connectControlEndpoint(new EventTarget(), registry, readyEvents, send);

    await endpoint.apply([
      { objectId: "first-0", value: 3 },
      { objectId: "second-0", value: 4 },
    ]);

    expect(send).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledWith({
      objectIds: ["first-0", "second-0"],
      values: [3, 4],
    });
  });

  test("keeps anywidget model references out of native control snapshots", () => {
    const registry = new FakeRegistry();
    registry.set("slider-0", 3);
    registry.set("widget-0", { model_id: "runtime-local-model" });

    expect(
      connectControlEndpoint(new EventTarget(), registry, readyEvents, async () => null).snapshot(),
    ).toEqual([{ objectId: "slider-0", value: 3 }]);
  });
});
