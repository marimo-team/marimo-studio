import { describe, expect, test, vi } from "vite-plus/test";

vi.mock("../src/upstream/controls.ts", () => ({
  MarimoValueReadyEvent: {
    TYPE: "ready",
    is: (event: Event) => "detail" in event,
  },
}));

import { connectControlEndpoint, type ControlEndpoint } from "../src/control-endpoint.ts";

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

const endpoint = (
  registry: FakeRegistry,
  sendControlValues: (request: { objectIds: string[]; values: unknown[] }) => Promise<unknown>,
  document = new EventTarget(),
): ControlEndpoint => {
  const frame = {
    contentWindow: {
      document,
      _marimo_private_UIElementRegistry: registry,
      _marimo_private_RuntimeState: { _sendComponentValues: sendControlValues },
    },
  } as unknown as HTMLIFrameElement;
  const connected = connectControlEndpoint(frame);
  if (!connected) {
    throw new Error("Expected the control endpoint to connect");
  }
  return connected;
};

describe("Control endpoint", () => {
  test("retains an update before the target control mounts", async () => {
    const registry = new FakeRegistry();
    const send = vi.fn(async () => null);
    const controls = endpoint(registry, send);

    await controls.apply([{ objectId: "slider-0", value: 4 }]);

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
    const controls = endpoint(registry, async () => null);
    const updates: unknown[] = [];
    controls.subscribe((update) => updates.push(update));

    registry.registerInstance("slider-0", { value: 7 } as HTMLElement & { value: number });

    expect(updates).toEqual([{ objectId: "slider-0", value: 7 }]);
  });

  test("applies a snapshot with one kernel request", async () => {
    const registry = new FakeRegistry();
    registry.set("first-0", 1);
    registry.set("second-0", 2);
    const send = vi.fn(async () => null);
    const controls = endpoint(registry, send);

    await controls.apply([
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

    expect(endpoint(registry, async () => null).snapshot()).toEqual([
      { objectId: "slider-0", value: 3 },
    ]);
  });

  test("shares one registration broker across out-of-order endpoint disposal", () => {
    const registry = new FakeRegistry();
    const original = registry.registerInstance;
    const first = endpoint(registry, async () => null);
    const broker = registry.registerInstance;
    const second = endpoint(registry, async () => null);
    const firstUpdates: unknown[] = [];
    const secondUpdates: unknown[] = [];
    first.subscribe((update) => firstUpdates.push(update));
    second.subscribe((update) => secondUpdates.push(update));

    expect(registry.registerInstance).toBe(broker);
    first.dispose();
    expect(registry.registerInstance).toBe(broker);

    registry.registerInstance("slider-0", { value: 7 } as HTMLElement & { value: number });

    expect(firstUpdates).toEqual([]);
    expect(secondUpdates).toEqual([{ objectId: "slider-0", value: 7 }]);
    expect(registry.messages).toEqual([
      {
        objectId: "slider-0",
        message: { type: "marimo-ui-value-update", value: 7 },
      },
    ]);

    second.dispose();
    expect(registry.registerInstance).toBe(original);
  });

  test("retries broker disposal after another registry owner unwinds", () => {
    const registry = new FakeRegistry();
    const original = registry.registerInstance;
    const controls = endpoint(registry, async () => null);
    const broker = registry.registerInstance;
    const foreign = function (this: FakeRegistry, objectId: string, instance: HTMLElement) {
      return broker.call(this, objectId, instance);
    };
    registry.registerInstance = foreign;

    expect(() => controls.dispose()).toThrow("changed before endpoint disposal");
    expect(registry.registerInstance).toBe(foreign);

    registry.registerInstance = broker;
    controls.dispose();
    expect(registry.registerInstance).toBe(original);

    const replacement = endpoint(registry, async () => null);
    registry.registerInstance("slider-0", { value: 7 } as HTMLElement & { value: number });
    expect(registry.messages).toHaveLength(1);
    replacement.dispose();
  });
});
