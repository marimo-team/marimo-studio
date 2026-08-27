import { z } from "zod";

import type { UIElementRegistry as MarimoUIElementRegistry } from "./upstream/controls.ts";

type ControlValue = Parameters<MarimoUIElementRegistry["set"]>[1];
type ControlMessage = Parameters<MarimoUIElementRegistry["broadcastMessage"]>[1];

export interface EmbeddedControlRegistry<TId> {
  readonly entries: {
    delete(objectId: TId): boolean;
    keys(): MapIterator<TId>;
  };
  has(objectId: TId): boolean;
  set(objectId: TId, value: ControlValue): void;
  registerInstance(objectId: TId, instance: HTMLElement): void;
  broadcastMessage(objectId: TId, message: ControlMessage, buffers: readonly DataView[]): void;
  broadcastValueUpdate(initiator: HTMLElement, objectId: TId, value: ControlValue): void;
  removeElementsByCell(cellId: string): void;
}

const configuredRegistries = new WeakSet<object>();
const replacementResets = new WeakMap<object, Set<unknown>>();
const controlUpdateSchema = z.object({
  type: z.literal("marimo-ui-value-update"),
  value: z.unknown().nonoptional(),
});

export const retainUnmountedControlValues = <TId>(registry: EmbeddedControlRegistry<TId>): void => {
  if (configuredRegistries.has(registry)) {
    return;
  }
  const reset = replacementResets.get(registry) ?? new Set<TId>();
  const generations = new Map<TId, string>();
  replacementResets.set(registry, reset);
  const set = registry.set.bind(registry);
  registry.set = (objectId, value) => {
    if (reset.has(objectId)) {
      return;
    }
    set(objectId, value);
  };
  const registerInstance = registry.registerInstance.bind(registry);
  registry.registerInstance = (objectId, instance) => {
    const randomId = instance.parentElement?.getAttribute("random-id");
    const previousGeneration = generations.get(objectId);
    if (
      reset.has(objectId) &&
      (randomId === null ||
        randomId === undefined ||
        (previousGeneration !== undefined && previousGeneration === randomId))
    ) {
      return;
    }
    const replaced =
      randomId !== null &&
      randomId !== undefined &&
      previousGeneration !== undefined &&
      previousGeneration !== randomId;
    const replacing = reset.has(objectId) || replaced;
    if (replacing) {
      registry.entries.delete(objectId);
    }
    reset.delete(objectId);
    try {
      registerInstance(objectId, instance);
    } catch (error) {
      if (replacing) {
        registry.entries.delete(objectId);
        reset.add(objectId);
      }
      throw error;
    }
    if (randomId) {
      generations.set(objectId, randomId);
    }
  };
  const removeElementsByCell = registry.removeElementsByCell.bind(registry);
  registry.removeElementsByCell = (cellId) => {
    for (const objectId of registry.entries.keys()) {
      if (String(objectId).startsWith(`${cellId}-`)) {
        reset.add(objectId);
      }
    }
    removeElementsByCell(cellId);
  };
  const broadcast = registry.broadcastMessage.bind(registry);
  registry.broadcastMessage = (objectId, message, buffers) => {
    if (reset.has(objectId)) {
      return;
    }
    const update = controlUpdateSchema.safeParse(message);
    if (!registry.has(objectId) && update.success) {
      registry.set(objectId, update.data.value);
    }
    broadcast(objectId, message, buffers);
  };
  const broadcastValueUpdate = registry.broadcastValueUpdate.bind(registry);
  registry.broadcastValueUpdate = (initiator, objectId, value) => {
    if (reset.has(objectId)) {
      return;
    }
    broadcastValueUpdate(initiator, objectId, value);
  };
  configuredRegistries.add(registry);
};

export const suppressReplacedControlValues = <TId>(
  registry: EmbeddedControlRegistry<TId>,
  objectIds: readonly TId[],
): void => {
  const reset = replacementResets.get(registry) ?? new Set<TId>();
  objectIds.forEach((objectId) => reset.add(objectId));
  replacementResets.set(registry, reset);
};
