// @vitest-environment jsdom

import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import type { UIElementId } from "../src/upstream/controls.ts";

import { connectControlEndpoint } from "../src/control-endpoint.ts";
import { createPreparedUiValues, installPreparedControlBridge } from "../src/prepared-controls.ts";
import { UI_ELEMENT_REGISTRY } from "../src/upstream/controls.ts";

// SAFETY: The fixture follows Marimo's `<cell-id>-<suffix>` UI object identity.
const objectId = "prepared-cell-control" as UIElementId;
// SAFETY: The fixture follows Marimo's `<cell-id>-<suffix>` UI object identity.
const siblingObjectId = "prepared-output-control" as UIElementId;
// SAFETY: The fixture follows Marimo's `<cell-id>-<suffix>` UI object identity.
const inactiveObjectId = "prepared-inactive-control" as UIElementId;
// SAFETY: This value exercises an inherited JavaScript object key at the registry boundary.
const inheritedObjectId = "toString" as UIElementId;
let stop: (() => void) | undefined;
let disposeValues: (() => void) | undefined;

afterEach(() => {
  stop?.();
  disposeValues?.();
  stop = undefined;
  disposeValues = undefined;
  [objectId, siblingObjectId, inactiveObjectId, inheritedObjectId].forEach((id) =>
    UI_ELEMENT_REGISTRY.entries.delete(id),
  );
  delete window._marimo_private_RuntimeState;
});

test("prepared UI values stage, roll back, clear, and restore registry ownership", () => {
  UI_ELEMENT_REGISTRY.set(objectId, 1);
  const element = document.createElement("div");
  UI_ELEMENT_REGISTRY.registerInstance(objectId, element);
  const originalEntry = UI_ELEMENT_REGISTRY.entries.get(objectId);
  const values = createPreparedUiValues();
  disposeValues = values.dispose;

  const two = values.stage({ [objectId]: 2 });
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), 2);
  assert.equal(UI_ELEMENT_REGISTRY.entries.get(objectId), originalEntry);
  assert.ok(UI_ELEMENT_REGISTRY.entries.get(objectId)?.elements.has(element));
  two.commit();

  const three = values.stage({ [objectId]: 3 });
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), 3);
  three.rollback();
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), 2);

  const committedThree = values.stage({ [objectId]: 3 });
  committedThree.commit();
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), 3);

  const empty = values.stage({});
  assert.equal(UI_ELEMENT_REGISTRY.has(objectId), false);
  empty.commit();

  values.dispose();
  disposeValues = undefined;
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), 1);
  assert.equal(UI_ELEMENT_REGISTRY.entries.get(objectId), originalEntry);
  assert.ok(UI_ELEMENT_REGISTRY.entries.get(objectId)?.elements.has(element));
});

test("prepared UI value snapshots capture browser-local values", () => {
  const values = createPreparedUiValues();
  disposeValues = values.dispose;
  values.stage({ [objectId]: "published" }).commit();
  const element = document.createElement("input");
  UI_ELEMENT_REGISTRY.registerInstance(objectId, element);

  UI_ELEMENT_REGISTRY.broadcastValueUpdate(element, objectId, "local draft");

  assert.deepEqual(values.snapshot(), { [objectId]: "local draft" });
});

test("prepared controls satisfy the peer endpoint and restore its private sender", async () => {
  UI_ELEMENT_REGISTRY.set(objectId, "one");
  const userInputs: Array<{ objectId: string; value: unknown }> = [];
  const peerInputs: Array<{ objectId: string; value: unknown }> = [];
  const previousBindings = {
    "existing-control": { input: "existing", path: [] },
  } as const;
  window._marimo_private_RuntimeState = { _controlBindings: previousBindings };
  const bridge = installPreparedControlBridge({
    onControlInput: (input) => userInputs.push(input),
    onPeerControlInput: (input) => peerInputs.push(input),
  });
  stop = bridge.dispose;
  bridge.updateControlBindings({
    [objectId]: {
      input: "scale",
      path: [{ kind: "key", value: "west" }],
    },
  });
  const values = createPreparedUiValues();
  disposeValues = values.dispose;
  values.stage({ [objectId]: "one" }).commit();
  const frame = document.createElement("iframe");
  document.body.append(frame);
  Object.assign(frame.contentWindow!, {
    _marimo_private_UIElementRegistry: UI_ELEMENT_REGISTRY,
    _marimo_private_RuntimeState: window._marimo_private_RuntimeState,
  });
  const endpoint = connectControlEndpoint(frame);

  assert.ok(endpoint);
  const bindingUpdates: unknown[] = [];
  const stopBindings = endpoint.subscribeControlBindings((bindings) =>
    bindingUpdates.push(bindings),
  );
  bridge.updateControlBindings({
    [objectId]: {
      input: "gain",
      path: [{ kind: "key", value: "west" }],
    },
  });
  assert.deepEqual(endpoint.controlBindings(), {
    [objectId]: {
      input: "gain",
      path: [{ kind: "key", value: "west" }],
    },
  });
  assert.deepEqual(bindingUpdates, [endpoint.controlBindings()]);
  assert.deepEqual(endpoint.snapshot(), [{ objectId, value: "one" }]);
  await endpoint.applyLocal([{ objectId, value: "two" }]);
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), "two");
  assert.deepEqual(userInputs, []);
  assert.deepEqual(peerInputs, []);

  bridge.updateControlBindings({
    [objectId]: {
      input: "gain",
      path: [{ kind: "key", value: "west" }],
    },
    [siblingObjectId]: {
      input: "gain",
      path: [{ kind: "key", value: "west" }],
    },
  });
  values.stage({ [objectId]: "two", [siblingObjectId]: "two" }).commit();
  await endpoint.apply([
    { objectId, value: "sent" },
    { objectId: siblingObjectId, value: "sent" },
  ]);
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(objectId), "sent");
  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(siblingObjectId), "sent");
  assert.deepEqual(userInputs, []);
  assert.deepEqual(peerInputs, [{ objectId, value: "sent" }]);

  const wrapper = document.createElement("marimo-ui-element");
  wrapper.setAttribute("object-id", objectId);
  const input = document.createElement("button");
  wrapper.append(input);
  document.body.append(wrapper);
  input.dispatchEvent(
    new CustomEvent("marimo-value-input", {
      bubbles: true,
      composed: true,
      detail: { element: input, value: "three" },
    }),
  );
  assert.deepEqual(userInputs, [{ objectId, value: "three" }]);
  assert.deepEqual(peerInputs, [{ objectId, value: "sent" }]);

  endpoint.dispose();
  stopBindings();
  wrapper.remove();
  frame.remove();
  stop();
  stop = undefined;
  assert.equal(window._marimo_private_RuntimeState?._controlBindings, previousBindings);
  assert.equal(connectControlEndpoint(frame), undefined);
  delete window._marimo_private_RuntimeState;
});

test("prepared controls mirror active semantic siblings once", () => {
  const received: Array<{ objectId: string; value: unknown }> = [];
  const bridge = installPreparedControlBridge({
    onControlInput: (input) => received.push(input),
  });
  stop = bridge.dispose;
  const binding = {
    input: "filters",
    path: [{ kind: "element" as const }, { kind: "key" as const, value: "detail" }],
  };
  bridge.updateControlBindings({
    [objectId]: binding,
    [siblingObjectId]: binding,
    [inactiveObjectId]: binding,
  });
  const values = createPreparedUiValues();
  disposeValues = values.dispose;
  values.stage({ [objectId]: "ready", [siblingObjectId]: "ready" }).commit();

  const wrapper = document.createElement("marimo-ui-element");
  wrapper.setAttribute("object-id", objectId);
  const input = document.createElement("button");
  wrapper.append(input);
  document.body.append(wrapper);
  input.dispatchEvent(
    new CustomEvent("marimo-value-input", {
      bubbles: true,
      composed: true,
      detail: { element: input, value: "from cell" },
    }),
  );

  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(siblingObjectId), "from cell");
  assert.equal(UI_ELEMENT_REGISTRY.has(inactiveObjectId), false);
  assert.deepEqual(received, [{ objectId, value: "from cell" }]);

  wrapper.remove();
});

test("prepared controls keep an inherited unbound object key local", () => {
  const received: Array<{ objectId: string; value: unknown }> = [];
  const bridge = installPreparedControlBridge({
    onControlInput: (input) => received.push(input),
  });
  stop = bridge.dispose;
  bridge.updateControlBindings({
    [siblingObjectId]: { input: "filters", path: [] },
  });
  UI_ELEMENT_REGISTRY.set(siblingObjectId, "ready");

  const wrapper = document.createElement("marimo-ui-element");
  wrapper.setAttribute("object-id", inheritedObjectId);
  const input = document.createElement("button");
  wrapper.append(input);
  document.body.append(wrapper);
  input.dispatchEvent(
    new CustomEvent("marimo-value-input", {
      bubbles: true,
      composed: true,
      detail: { element: input, value: "local" },
    }),
  );

  assert.equal(UI_ELEMENT_REGISTRY.lookupValue(siblingObjectId), "ready");
  assert.deepEqual(received, [{ objectId: inheritedObjectId, value: "local" }]);
  wrapper.remove();
});
