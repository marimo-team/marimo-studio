import { MarimoValueInputEvent } from "@marimo-team/frontend/unstable_internal/core/dom/events";
import { getUIElementObjectId } from "@marimo-team/frontend/unstable_internal/core/dom/ui-element";

import type {
  ControlBinding,
  ControlBindings,
  ControlBindingsListener,
  SendControlValues,
  SubscribeControlBindings,
} from "./control-endpoint-core.ts";
import type { EmbeddedJsonValue } from "./embedded-json.ts";
import type { UIElementId } from "./upstream/controls.ts";

import { parseControlBindings } from "./control-endpoint-core.ts";
import { jsonObjectSchema, parseEmbeddedJsonValue } from "./embedded-json.ts";
import { UI_ELEMENT_REGISTRY } from "./upstream/controls.ts";

export interface PreparedControlInput {
  readonly objectId: string;
  readonly value: EmbeddedJsonValue;
}

export type PreparedControlInputListener = (input: PreparedControlInput) => void;

export interface PreparedControlBridgeOptions {
  readonly onControlInput?: PreparedControlInputListener;
  readonly onPeerControlInput?: PreparedControlInputListener;
}

export interface PreparedUiValueStage {
  commit(): void;
  rollback(): void;
}

export interface PreparedUiValuesHandle {
  snapshot(): Readonly<Record<string, EmbeddedJsonValue>>;
  stage(values: Readonly<Record<string, EmbeddedJsonValue>>): PreparedUiValueStage;
  dispose(): void;
}

export interface PreparedControlBridgeHandle {
  updateControlBindings(bindings: ControlBindings): void;
  dispose(): void;
}

interface PreparedRuntimeState {
  _controlBindings?: ControlBindings;
  _sendComponentValues?: SendControlValues;
  _subscribeControlBindings?: SubscribeControlBindings;
}

// SAFETY: This facade owns the documented Marimo private bridge on the browser global.
const browser = globalThis as typeof globalThis & {
  _marimo_private_RuntimeState?: PreparedRuntimeState;
};

type RegistryEntry =
  typeof UI_ELEMENT_REGISTRY.entries extends Map<UIElementId, infer Entry> ? Entry : never;

interface RegistryEntrySnapshot {
  readonly entry: RegistryEntry | null;
  readonly value: RegistryEntry["value"];
}

const registryId = (objectId: string): UIElementId => {
  // SAFETY: Prepared resource IDs originate from Marimo's serialized UI registry.
  return objectId as UIElementId;
};

const snapshotEntry = (objectId: string): RegistryEntrySnapshot => {
  const entry = UI_ELEMENT_REGISTRY.entries.get(registryId(objectId)) ?? null;
  return { entry, value: entry?.value };
};

const setPreparedValue = (objectId: string, value: EmbeddedJsonValue): void => {
  const id = registryId(objectId);
  if (!UI_ELEMENT_REGISTRY.has(id)) {
    UI_ELEMENT_REGISTRY.set(id, value);
    return;
  }
  UI_ELEMENT_REGISTRY.broadcastMessage(id, { type: "marimo-ui-value-update", value }, []);
};

const sameControlBinding = (left: ControlBinding, right: ControlBinding): boolean =>
  left.input === right.input &&
  left.path.length === right.path.length &&
  left.path.every((step, index) => {
    const candidate = right.path[index];
    if (candidate === undefined || step.kind !== candidate.kind) {
      return false;
    }
    if (step.kind === "element") {
      return true;
    }
    return candidate.kind !== "element" && step.value === candidate.value;
  });

const ownControlBinding = (
  bindings: ControlBindings,
  objectId: string,
): ControlBinding | undefined =>
  Object.hasOwn(bindings, objectId) ? bindings[objectId] : undefined;

const samePreparedValue = (left: EmbeddedJsonValue, right: EmbeddedJsonValue): boolean => {
  if (left === right) {
    return true;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => samePreparedValue(value, right[index]!))
    );
  }
  const leftObject = jsonObjectSchema.safeParse(left);
  const rightObject = jsonObjectSchema.safeParse(right);
  if (!leftObject.success || !rightObject.success) {
    return false;
  }
  const keys = Object.keys(leftObject.data);
  return (
    keys.length === Object.keys(rightObject.data).length &&
    keys.every(
      (key) =>
        Object.hasOwn(rightObject.data, key) &&
        samePreparedValue(leftObject.data[key]!, rightObject.data[key]!),
    )
  );
};

const restoreEntries = (entries: ReadonlyMap<string, RegistryEntrySnapshot>): void => {
  entries.forEach(({ entry, value }, objectId) => {
    const id = registryId(objectId);
    if (entry === null) {
      UI_ELEMENT_REGISTRY.entries.delete(id);
    } else {
      UI_ELEMENT_REGISTRY.entries.set(id, entry);
      UI_ELEMENT_REGISTRY.broadcastMessage(id, { type: "marimo-ui-value-update", value }, []);
    }
  });
};

export const createPreparedUiValues = (): PreparedUiValuesHandle => {
  const originalEntries = new Map<string, RegistryEntrySnapshot>();
  let activeIds = new Set<string>();
  let pendingRollback: (() => void) | undefined;
  let disposed = false;

  const snapshot = (): Readonly<Record<string, EmbeddedJsonValue>> => {
    if (disposed) {
      throw new Error("Prepared UI values are disposed");
    }
    if (pendingRollback !== undefined) {
      throw new Error("Prepared UI values cannot be snapshotted during staging");
    }
    return Object.fromEntries(
      [...activeIds].map((objectId) => {
        const entry = UI_ELEMENT_REGISTRY.entries.get(registryId(objectId));
        if (entry === undefined) {
          throw new Error(`Prepared UI object ${JSON.stringify(objectId)} is missing`);
        }
        return [objectId, parseEmbeddedJsonValue(structuredClone(entry.value))];
      }),
    );
  };

  const stage = (values: Readonly<Record<string, EmbeddedJsonValue>>): PreparedUiValueStage => {
    if (disposed) {
      throw new Error("Prepared UI values are disposed");
    }
    if (pendingRollback !== undefined) {
      throw new Error("A prepared UI value stage is already active");
    }
    const next: Record<string, EmbeddedJsonValue> = structuredClone(values);
    const nextIds = new Set(Object.keys(next));
    const affectedIds = new Set([...activeIds, ...nextIds]);
    const before = new Map<string, RegistryEntrySnapshot>();
    affectedIds.forEach((objectId) => {
      const entry = snapshotEntry(objectId);
      before.set(objectId, entry);
      if (!originalEntries.has(objectId)) {
        originalEntries.set(objectId, entry);
      }
    });
    const rollback = (): void => {
      if (pendingRollback !== rollback) {
        return;
      }
      restoreEntries(before);
      pendingRollback = undefined;
    };
    pendingRollback = rollback;
    try {
      activeIds.forEach((objectId) => {
        if (!nextIds.has(objectId)) {
          UI_ELEMENT_REGISTRY.entries.delete(registryId(objectId));
        }
      });
      Object.entries(next).forEach(([objectId, value]) => {
        setPreparedValue(objectId, value);
      });
    } catch (error) {
      rollback();
      throw error;
    }
    let settled = false;
    return Object.freeze({
      commit() {
        if (settled) {
          return;
        }
        settled = true;
        activeIds = nextIds;
        pendingRollback = undefined;
      },
      rollback() {
        if (settled) {
          return;
        }
        settled = true;
        rollback();
      },
    });
  };

  const dispose = (): void => {
    if (disposed) {
      return;
    }
    pendingRollback?.();
    disposed = true;
    restoreEntries(originalEntries);
    originalEntries.clear();
    activeIds = new Set();
  };

  return Object.freeze({ snapshot, stage, dispose });
};

export const subscribePreparedControlInputs = (
  listener: PreparedControlInputListener,
): (() => void) => {
  const handleInput = (event: Event): void => {
    if (!MarimoValueInputEvent.is(event)) {
      return;
    }
    const objectId = getUIElementObjectId(event.detail.element);
    if (objectId === null) {
      return;
    }
    let value: EmbeddedJsonValue;
    try {
      value = parseEmbeddedJsonValue(event.detail.value);
    } catch {
      return;
    }
    listener({ objectId, value });
  };
  document.addEventListener(MarimoValueInputEvent.TYPE, handleInput);
  return () => document.removeEventListener(MarimoValueInputEvent.TYPE, handleInput);
};

export const installPreparedControlBridge = (
  options: PreparedControlBridgeOptions,
): PreparedControlBridgeHandle => {
  const previousState = browser._marimo_private_RuntimeState;
  const state = previousState ?? {};
  const previousBindings = state._controlBindings;
  const previousSender = state._sendComponentValues;
  const previousSubscribeBindings = state._subscribeControlBindings;
  const bindingListeners = new Set<ControlBindingsListener>();
  const sendComponentValues: SendControlValues = async ({ objectIds, values }) => {
    const inputs: PreparedControlInput[] = [];
    objectIds.forEach((objectId, index) => {
      const value = values[index];
      if (value === undefined) {
        return;
      }
      let parsed: EmbeddedJsonValue;
      try {
        parsed = parseEmbeddedJsonValue(value);
      } catch {
        return;
      }
      const binding = ownControlBinding(controlBindings, objectId);
      const duplicate =
        binding === undefined
          ? undefined
          : inputs.find((input) => {
              const candidate = ownControlBinding(controlBindings, input.objectId);
              return candidate !== undefined && sameControlBinding(binding, candidate);
            });
      if (duplicate !== undefined) {
        if (!samePreparedValue(duplicate.value, parsed)) {
          throw new Error("Prepared peer controls supplied conflicting semantic values");
        }
        return;
      }
      inputs.push({ objectId, value: parsed });
    });
    inputs.forEach((input) => {
      try {
        options.onPeerControlInput?.(input);
      } catch {
        return;
      }
    });
    return null;
  };
  let controlBindings = parseControlBindings({});
  const subscribeControlBindings: SubscribeControlBindings = (bindingListener) => {
    bindingListeners.add(bindingListener);
    return () => bindingListeners.delete(bindingListener);
  };
  state._controlBindings = controlBindings;
  state._sendComponentValues = sendComponentValues;
  state._subscribeControlBindings = subscribeControlBindings;
  browser._marimo_private_RuntimeState = state;
  const restoreState = (): void => {
    if (browser._marimo_private_RuntimeState !== state) {
      return;
    }
    const errors: Error[] = [];
    if (state._sendComponentValues === sendComponentValues) {
      if (previousSender === undefined) {
        delete state._sendComponentValues;
      } else {
        state._sendComponentValues = previousSender;
      }
    } else {
      errors.push(new Error("The prepared control sender changed before disposal"));
    }
    if (state._controlBindings === controlBindings) {
      if (previousBindings === undefined) {
        delete state._controlBindings;
      } else {
        state._controlBindings = previousBindings;
      }
    } else {
      errors.push(new Error("The prepared control bindings changed before disposal"));
    }
    if (state._subscribeControlBindings === subscribeControlBindings) {
      if (previousSubscribeBindings === undefined) {
        delete state._subscribeControlBindings;
      } else {
        state._subscribeControlBindings = previousSubscribeBindings;
      }
    } else {
      errors.push(new Error("The prepared control binding subscriber changed before disposal"));
    }
    bindingListeners.clear();
    if (previousState === undefined) {
      delete browser._marimo_private_RuntimeState;
    }
    if (errors.length === 1) {
      throw errors[0];
    }
    if (errors.length > 1) {
      throw new AggregateError(errors, "Prepared control state changed before disposal");
    }
  };
  const receiveInput = (input: PreparedControlInput): void => {
    const source = ownControlBinding(controlBindings, input.objectId);
    if (source !== undefined) {
      Object.entries(controlBindings).forEach(([objectId, binding]) => {
        if (
          objectId !== input.objectId &&
          UI_ELEMENT_REGISTRY.has(registryId(objectId)) &&
          sameControlBinding(source, binding)
        ) {
          setPreparedValue(objectId, input.value);
        }
      });
    }
    options.onControlInput?.(input);
  };
  let stopInput: () => void;
  try {
    stopInput = subscribePreparedControlInputs(receiveInput);
  } catch (error) {
    try {
      restoreState();
    } catch (rollbackError) {
      throw new AggregateError(
        [error, rollbackError],
        "Prepared control bridge setup and rollback failed",
      );
    }
    throw error;
  }
  let installed = true;
  const dispose = (): void => {
    if (!installed) {
      return;
    }
    installed = false;
    const errors: unknown[] = [];
    try {
      stopInput();
    } catch (error) {
      errors.push(error);
    }
    try {
      restoreState();
    } catch (error) {
      errors.push(error);
    }
    if (errors.length === 1) {
      throw errors[0];
    }
    if (errors.length > 1) {
      throw new AggregateError(errors, "Prepared control bridge disposal failed");
    }
  };
  return Object.freeze({
    updateControlBindings(bindings: ControlBindings) {
      if (!installed) {
        return;
      }
      controlBindings = parseControlBindings(bindings);
      state._controlBindings = controlBindings;
      bindingListeners.forEach((bindingListener) => bindingListener(controlBindings));
    },
    dispose,
  });
};
