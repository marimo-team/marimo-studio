import { z } from "zod";

import type { UIElementRegistry as MarimoUIElementRegistry } from "./upstream/controls.ts";

type ControlValue = Parameters<MarimoUIElementRegistry["set"]>[1];
type ControlMessage = Parameters<MarimoUIElementRegistry["broadcastMessage"]>[1];

interface UIElementEntry {
  value: ControlValue;
}

export interface ControlRegistry {
  readonly entries: ReadonlyMap<string, UIElementEntry>;
  has(objectId: string): boolean;
  lookupValue(objectId: string): ControlValue;
  set(objectId: string, value: ControlValue): void;
  registerInstance: (objectId: string, instance: HTMLElement) => void;
  broadcastMessage(objectId: string, message: ControlMessage, buffers: readonly DataView[]): void;
}

export interface ControlUpdate {
  objectId: string;
  value: ControlValue;
}

export interface ControlEndpoint {
  snapshot(): readonly ControlUpdate[];
  subscribe(listener: (update: ControlUpdate) => void): () => void;
  apply(updates: readonly ControlUpdate[]): Promise<void>;
  dispose(): void;
}

export type SendControlValues = (request: {
  objectIds: string[];
  values: ControlValue[];
}) => Promise<null>;

export interface ReadyEvents {
  type: string;
  objectId(event: Event): string | undefined;
}

const widgetModelReferenceSchema = z.strictObject({ model_id: z.string().min(1) });

const isNativeControlValue = (value: ControlValue): boolean =>
  !widgetModelReferenceSchema.safeParse(value).success;

type RegistrationSubscriber = (objectId: string) => void;

interface RegistrationBroker {
  readonly original: ControlRegistry["registerInstance"];
  readonly observeRegistration: ControlRegistry["registerInstance"];
  readonly subscribers: Set<RegistrationSubscriber>;
}

const registrationBrokers = new WeakMap<ControlRegistry, RegistrationBroker>();

const subscribeRegistrations = (
  registry: ControlRegistry,
  subscriber: RegistrationSubscriber,
): (() => void) => {
  let broker = registrationBrokers.get(registry);
  if (!broker) {
    const original = registry.registerInstance;
    const registerInstance = original.bind(registry);
    const subscribers = new Set<RegistrationSubscriber>();
    const observeRegistration: ControlRegistry["registerInstance"] = (objectId, instance) => {
      registerInstance(objectId, instance);
      const value = registry.lookupValue(objectId);
      if (!isNativeControlValue(value)) {
        return;
      }
      registry.broadcastMessage(objectId, { type: "marimo-ui-value-update", value }, []);
      subscribers.forEach((notify) => notify(objectId));
    };
    broker = { original, observeRegistration, subscribers };
    registrationBrokers.set(registry, broker);
    registry.registerInstance = observeRegistration;
  }
  broker.subscribers.add(subscriber);
  let subscribed = true;
  return () => {
    if (!subscribed) {
      return;
    }
    if (broker.subscribers.size > 1) {
      broker.subscribers.delete(subscriber);
      subscribed = false;
      return;
    }
    if (registry.registerInstance !== broker.observeRegistration) {
      throw new Error("The Marimo control registry changed before endpoint disposal");
    }
    registry.registerInstance = broker.original;
    broker.subscribers.delete(subscriber);
    registrationBrokers.delete(registry);
    subscribed = false;
  };
};

export const connectControlEndpoint = (
  document: EventTarget,
  registry: ControlRegistry,
  readyEvents: ReadyEvents,
  sendControlValues: SendControlValues,
): ControlEndpoint => {
  let applying = false;
  let applyTail = Promise.resolve();
  const disposers = new Set<() => void>();
  const listeners = new Set<(update: ControlUpdate) => void>();
  const notify = (objectId: string) => {
    if (applying || !registry.has(objectId)) {
      return;
    }
    const value = registry.lookupValue(objectId);
    if (isNativeControlValue(value)) {
      listeners.forEach((listener) => listener({ objectId, value }));
    }
  };
  const releaseRegistrations = subscribeRegistrations(registry, notify);
  const apply = async (updates: readonly ControlUpdate[]): Promise<void> => {
    const accepted: ControlUpdate[] = [];
    const created: string[] = [];
    applying = true;
    try {
      for (const update of updates) {
        if (!registry.has(update.objectId)) {
          registry.set(update.objectId, update.value);
          created.push(update.objectId);
        }
        if (!registry.has(update.objectId)) {
          continue;
        }
        accepted.push(update);
      }
      if (accepted.length === 0) {
        return;
      }
      try {
        await sendControlValues({
          objectIds: accepted.map(({ objectId }) => objectId),
          values: accepted.map(({ value }) => value),
        });
      } catch (error) {
        // SAFETY: Marimo exposes entries as a Map. ControlRegistry narrows it
        // to read-only access outside this rollback boundary.
        const entries = registry.entries as Map<string, UIElementEntry>;
        created.forEach((objectId) => entries.delete(objectId));
        throw error;
      }
      accepted.forEach((update) =>
        registry.broadcastMessage(
          update.objectId,
          { type: "marimo-ui-value-update", value: update.value },
          [],
        ),
      );
    } finally {
      applying = false;
    }
  };
  return {
    snapshot: () =>
      Array.from(registry.entries, ([objectId, entry]) => ({ objectId, entry }))
        .filter(({ entry }) => isNativeControlValue(entry.value))
        .map(({ objectId, entry }) => ({ objectId, value: entry.value })),
    subscribe(listener) {
      const receive = (event: Event) => {
        const objectId = readyEvents.objectId(event);
        if (objectId) {
          notify(objectId);
        }
      };
      listeners.add(listener);
      document.addEventListener(readyEvents.type, receive);
      const dispose = () => {
        listeners.delete(listener);
        document.removeEventListener(readyEvents.type, receive);
        disposers.delete(dispose);
      };
      disposers.add(dispose);
      return dispose;
    },
    apply(updates) {
      if (updates.length === 0) {
        return Promise.resolve();
      }
      const operation = applyTail.then(() => apply(updates));
      applyTail = operation.catch(() => undefined);
      return operation;
    },
    dispose() {
      Array.from(disposers).forEach((dispose) => dispose());
      releaseRegistrations();
    },
  };
};
