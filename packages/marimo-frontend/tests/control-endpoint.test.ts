// @vitest-environment jsdom

import { UIElementId } from "@marimo-team/frontend/unstable_internal/core/cells/ids";
import { describe, expect, test, vi } from "vite-plus/test";

import type {
  ControlEndpoint,
  ControlRegistry,
  ControlUpdate,
  SendControlValues,
} from "../src/control-endpoint-core.ts";

import { connectControlEndpoint as connectCoreControlEndpoint } from "../src/control-endpoint-core.ts";
import { connectControlEndpoint as connectFrameControlEndpoint } from "../src/control-endpoint.ts";
import {
  retainUnmountedControlValues,
  suppressReplacedControlValues,
} from "../src/embedded-control-state.ts";
import { MarimoValueReadyEvent } from "../src/upstream/controls.ts";

type ControlValue = ControlUpdate["value"];
type ControlMessage = Parameters<ControlRegistry["broadcastMessage"]>[1];

interface RegistryEntry {
  value: ControlValue;
}

const initialValues = new WeakMap<HTMLElement, ControlValue>();

const controlElement = (value: ControlValue): HTMLElement => {
  const element = document.createElement("div");
  initialValues.set(element, value);
  return element;
};

const controlId = (value: string) => {
  const element = document.createElement("marimo-ui-element");
  element.setAttribute("object-id", value);
  const objectId = UIElementId.parse(element);
  if (!objectId) {
    throw new Error(`Expected a Marimo control ID for ${JSON.stringify(value)}`);
  }
  return objectId;
};

class FakeRegistry implements ControlRegistry {
  readonly entries = new Map<string, RegistryEntry>();
  readonly messages: Array<{ objectId: string; message: ControlMessage }> = [];

  has(objectId: string): boolean {
    return this.entries.has(objectId);
  }

  lookupValue(objectId: string): ControlValue {
    return this.entries.get(objectId)?.value;
  }

  set(objectId: string, value: ControlValue): void {
    this.entries.set(objectId, { value });
  }

  registerInstance(objectId: string, instance: HTMLElement): void {
    if (!this.entries.has(objectId)) {
      this.set(objectId, initialValues.get(instance));
    }
  }

  broadcastMessage(objectId: string, message: ControlMessage): void {
    this.messages.push({ objectId, message });
  }

  broadcastValueUpdate(_initiator: HTMLElement, _objectId: string, _value: ControlValue): void {}

  removeElementsByCell(cellId: string): void {
    for (const objectId of this.entries.keys()) {
      if (objectId.startsWith(`${cellId}-`)) {
        this.entries.delete(objectId);
      }
    }
  }
}

const endpoint = (
  registry: FakeRegistry,
  sendControlValues: SendControlValues,
): ControlEndpoint => {
  return connectCoreControlEndpoint(
    document,
    registry,
    { type: "ready", objectId: () => undefined },
    sendControlValues,
  );
};

describe("Control endpoint", () => {
  test("connects iframe globals and publishes real ready events", () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const browser = frame.contentWindow;
    if (!browser) {
      throw new Error("Expected the iframe to have a content window");
    }
    const objectId = controlId("slider-0");
    const registry = new FakeRegistry();
    registry.set(objectId, 7);
    browser._marimo_private_UIElementRegistry = registry;
    browser._marimo_private_RuntimeState = { _sendComponentValues: async () => null };

    const controls = connectFrameControlEndpoint(frame);
    if (!controls) {
      throw new Error("Expected the iframe control endpoint to connect");
    }
    const updates: ControlUpdate[] = [];
    controls.subscribe((update) => updates.push(update));
    browser.document.dispatchEvent(
      MarimoValueReadyEvent.create({
        detail: { objectId },
      }),
    );

    expect(updates).toEqual([{ objectId, value: 7 }]);
    controls.dispose();
    frame.remove();
  });

  test("leaves frames without Marimo control globals disconnected", () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    expect(connectFrameControlEndpoint(frame)).toBeUndefined();
    frame.remove();
  });

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

  test("keeps target controls unchanged when the kernel rejects an update", async () => {
    const registry = new FakeRegistry();
    registry.set("slider-0", 2);
    const send = vi.fn(async () => {
      throw new Error("kernel rejected update");
    });
    const controls = endpoint(registry, send);

    await expect(
      controls.apply([
        { objectId: "slider-0", value: 4 },
        { objectId: "pending-0", value: 5 },
      ]),
    ).rejects.toThrow("kernel rejected update");

    expect(registry.lookupValue("slider-0")).toBe(2);
    expect(registry.has("pending-0")).toBe(false);
    expect(registry.messages).toEqual([]);
  });

  test("keeps a replaced control's stale update out of the kernel", async () => {
    const registry = new FakeRegistry();
    retainUnmountedControlValues(registry);
    registry.set("replaced-0", 2);
    registry.set("live-0", 3);
    suppressReplacedControlValues(registry, ["replaced-0"]);
    registry.entries.delete("replaced-0");
    const send = vi.fn(async () => null);
    const controls = endpoint(registry, send);

    await controls.apply([
      { objectId: "replaced-0", value: 2 },
      { objectId: "live-0", value: 4 },
    ]);

    expect(registry.has("replaced-0")).toBe(false);
    expect(registry.messages).toEqual([
      {
        objectId: "live-0",
        message: { type: "marimo-ui-value-update", value: 4 },
      },
    ]);
    expect(send).toHaveBeenCalledWith({ objectIds: ["live-0"], values: [4] });
  });

  test("publishes a native control when it mounts after subscription", () => {
    const registry = new FakeRegistry();
    const controls = endpoint(registry, async () => null);
    const updates: ControlUpdate[] = [];
    controls.subscribe((update) => updates.push(update));

    registry.registerInstance("slider-0", controlElement(7));

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
    const firstUpdates: ControlUpdate[] = [];
    const secondUpdates: ControlUpdate[] = [];
    first.subscribe((update) => firstUpdates.push(update));
    second.subscribe((update) => secondUpdates.push(update));

    expect(registry.registerInstance).toBe(broker);
    first.dispose();
    expect(registry.registerInstance).toBe(broker);

    registry.registerInstance("slider-0", controlElement(7));

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
    registry.registerInstance("slider-0", controlElement(7));
    expect(registry.messages).toHaveLength(1);
    replacement.dispose();
  });
});
