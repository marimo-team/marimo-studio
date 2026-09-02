// @vitest-environment jsdom

import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  type EmbeddedControlRegistry,
  retainUnmountedControlValues,
  suppressReplacedControlValues,
} from "../src/embedded-control-state.ts";

type ControlValue = Parameters<EmbeddedControlRegistry<string>["set"]>[1];
type ControlMessage = Parameters<EmbeddedControlRegistry<string>["broadcastMessage"]>[1];

const initialValues = new WeakMap<HTMLElement, ControlValue>();
const failedRegistrations = new WeakSet<HTMLElement>();

const controlElement = (value: ControlValue, randomId = "generation"): HTMLElement => {
  const owner = document.createElement("marimo-ui-element");
  owner.setAttribute("random-id", randomId);
  const element = document.createElement("div");
  owner.append(element);
  initialValues.set(element, value);
  return element;
};

interface RegistryEntry {
  readonly elements: Set<HTMLElement>;
  value: ControlValue;
}

class Registry implements EmbeddedControlRegistry<string> {
  readonly entries = new Map<string, RegistryEntry>();
  readonly delivered: string[] = [];
  readonly published: string[] = [];

  has(objectId: string) {
    return this.entries.has(objectId);
  }

  set(objectId: string, value: ControlValue) {
    this.entries.set(objectId, { elements: new Set(), value });
  }

  registerInstance(objectId: string, instance: HTMLElement) {
    if (failedRegistrations.delete(instance)) {
      this.set(objectId, initialValues.get(instance));
      throw new Error("Control registration failed");
    }
    if (!this.has(objectId)) {
      this.set(objectId, initialValues.get(instance));
    }
    this.entries.get(objectId)?.elements.add(instance);
  }

  broadcastMessage(objectId: string, _message: ControlMessage, _buffers: readonly DataView[]) {
    if (this.has(objectId)) {
      this.delivered.push(objectId);
    }
  }

  broadcastValueUpdate(_initiator: HTMLElement, objectId: string, value: ControlValue) {
    const entry = this.entries.get(objectId);
    if (entry) {
      entry.value = value;
      this.published.push(objectId);
    }
  }

  removeElementsByCell(cellId: string) {
    for (const objectId of this.entries.keys()) {
      if (objectId.startsWith(`${cellId}-`)) {
        this.entries.delete(objectId);
      }
    }
  }

  value(objectId: string): ControlValue {
    return this.entries.get(objectId)?.value;
  }
}

test("peer values survive until their control mounts", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);

  registry.broadcastMessage("slider", { type: "marimo-ui-value-update", value: 8 }, []);

  assert.deepEqual(registry.value("slider"), 8);
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

test("a replaced control ignores old state until its new instance mounts", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);
  registry.set("slider", 2);
  suppressReplacedControlValues(registry, ["slider"]);
  registry.entries.delete("slider");

  registry.broadcastMessage("slider", { type: "marimo-ui-value-update", value: 2 }, []);
  registry.set("slider", 2);

  assert.deepEqual(registry.has("slider"), false);
  registry.registerInstance("slider", controlElement(1));
  registry.broadcastMessage("slider", { type: "marimo-ui-value-update", value: 1 }, []);
  assert.deepEqual(registry.value("slider"), 1);
  assert.deepEqual(registry.delivered, ["slider"]);
});

test("owner removal ignores old state until the replacement mounts", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);
  registry.set("owner-0", 2);
  registry.removeElementsByCell("owner");

  registry.broadcastMessage("owner-0", { type: "marimo-ui-value-update", value: 2 }, []);
  registry.set("owner-0", 2);

  assert.deepEqual(registry.has("owner-0"), false);
  registry.registerInstance("owner-0", controlElement(1));
  registry.broadcastMessage("owner-0", { type: "marimo-ui-value-update", value: 1 }, []);
  assert.deepEqual(registry.value("owner-0"), 1);
  assert.deepEqual(registry.delivered, ["owner-0"]);
});

test("a reused control node resets when its generation changes", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);
  const element = controlElement(2, "old");
  registry.registerInstance("owner-0", element);
  initialValues.set(element, 1);
  const owner = element.parentElement;
  if (!owner) {
    throw new Error("Expected the control element to have an owner");
  }
  owner.setAttribute("random-id", "new");

  registry.registerInstance("owner-0", element);

  assert.deepEqual(registry.value("owner-0"), 1);
});

test("only the current control generation can mount or publish", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);
  const retired = controlElement(2, "retired");
  registry.registerInstance("owner-0", retired);
  registry.removeElementsByCell("owner");

  registry.registerInstance("owner-0", retired);
  registry.broadcastValueUpdate(retired, "owner-0", 2);

  assert.deepEqual(registry.has("owner-0"), false);
  assert.deepEqual(registry.published, []);
  const replacement = controlElement(1, "replacement");
  registry.registerInstance("owner-0", replacement);
  registry.broadcastValueUpdate(replacement, "owner-0", 1);

  registry.registerInstance("owner-0", retired);
  registry.broadcastValueUpdate(retired, "owner-0", 9);

  assert.deepEqual(registry.value("owner-0"), 1);
  assert.deepEqual(registry.published, ["owner-0"]);
});

test("a failed replacement keeps stale writes blocked until retry", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);
  registry.registerInstance("owner-0", controlElement(2, "retired"));
  registry.removeElementsByCell("owner");
  const replacement = controlElement(1, "replacement");
  failedRegistrations.add(replacement);

  assert.throws(
    () => registry.registerInstance("owner-0", replacement),
    /Control registration failed/,
  );
  registry.set("owner-0", 2);
  registry.broadcastMessage("owner-0", { type: "marimo-ui-value-update", value: 2 }, []);

  assert.deepEqual(registry.has("owner-0"), false);
  registry.registerInstance("owner-0", replacement);
  assert.deepEqual(registry.value("owner-0"), 1);
});

test("control aliases from one generation share their current value", () => {
  const registry = new Registry();
  retainUnmountedControlValues(registry);
  registry.registerInstance("owner-0", controlElement(3, "shared"));

  registry.registerInstance("owner-0", controlElement(1, "shared"));

  assert.deepEqual(registry.value("owner-0"), 3);
});
