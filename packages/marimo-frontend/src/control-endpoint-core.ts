import { losslessRecordSchema } from "@marimo-team/portable-json/zod";
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

export interface ControlEvent extends ControlUpdate {
  readonly origin: "input" | "registration";
}

export type ControlPathStep =
  | { readonly kind: "element" }
  | { readonly kind: "index"; readonly value: number }
  | { readonly kind: "key"; readonly value: string };

export interface ControlBinding {
  readonly input: string;
  readonly path: readonly ControlPathStep[];
}

export type ControlBindings = Readonly<Record<string, ControlBinding>>;
export type ControlBindingsListener = (bindings: ControlBindings) => void;
export type SubscribeControlBindings = (listener: ControlBindingsListener) => () => void;
export type ControlTopologyListener = (objectId: string) => void;

export interface ControlEndpoint {
  controlBindings(): ControlBindings | undefined;
  subscribeControlBindings(listener: ControlBindingsListener): () => void;
  subscribeTopology(listener: ControlTopologyListener): () => void;
  snapshot(): readonly ControlUpdate[];
  subscribe(listener: (update: ControlEvent) => void): () => void;
  apply(updates: readonly ControlUpdate[]): Promise<void>;
  applyLocal(updates: readonly ControlUpdate[]): Promise<void>;
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
const controlPathStepSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("element") }),
  z.strictObject({ kind: z.literal("index"), value: z.int().nonnegative() }),
  z.strictObject({ kind: z.literal("key"), value: z.string() }),
]);
const controlBindingsSchema = losslessRecordSchema(
  z.string().min(1),
  z.strictObject({ input: z.string().min(1), path: z.array(controlPathStepSchema) }),
);

export const parseControlBindings = (value: ControlBindings): ControlBindings => {
  const parsed = controlBindingsSchema.parse(value);
  Object.values(parsed).forEach((binding) => Object.freeze(binding.path));
  Object.values(parsed).forEach(Object.freeze);
  return Object.freeze(parsed);
};

const isNativeControlValue = (value: ControlValue): boolean =>
  !widgetModelReferenceSchema.safeParse(value).success;

type RegistrationSubscriber = (objectId: string) => void;

interface RegistrationObserver {
  readonly topology: RegistrationSubscriber;
  readonly value: RegistrationSubscriber;
}

interface RegistrationBroker {
  readonly original: ControlRegistry["registerInstance"];
  readonly observeRegistration: ControlRegistry["registerInstance"];
  readonly subscribers: Set<RegistrationObserver>;
}

const registrationBrokers = new WeakMap<ControlRegistry, RegistrationBroker>();

const subscribeRegistrations = (
  registry: ControlRegistry,
  subscriber: RegistrationObserver,
): (() => void) => {
  let broker = registrationBrokers.get(registry);
  if (!broker) {
    const original = registry.registerInstance;
    const registerInstance = original.bind(registry);
    const subscribers = new Set<RegistrationObserver>();
    const observeRegistration: ControlRegistry["registerInstance"] = (objectId, instance) => {
      registerInstance(objectId, instance);
      subscribers.forEach(({ topology }) => topology(objectId));
      const value = registry.lookupValue(objectId);
      if (!isNativeControlValue(value)) {
        return;
      }
      registry.broadcastMessage(objectId, { type: "marimo-ui-value-update", value }, []);
      subscribers.forEach(({ value: notify }) => notify(objectId));
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
  readControlBindings: () => ControlBindings | undefined = () => undefined,
  subscribeControlBindings: SubscribeControlBindings = () => () => {},
): ControlEndpoint => {
  let applying = false;
  let applyTail = Promise.resolve();
  const disposers = new Set<() => void>();
  const listeners = new Set<(update: ControlEvent) => void>();
  const topologyListeners = new Set<ControlTopologyListener>();
  const notify = (objectId: string, origin: ControlEvent["origin"]) => {
    if (applying || !registry.has(objectId)) {
      return;
    }
    const value = registry.lookupValue(objectId);
    if (isNativeControlValue(value)) {
      listeners.forEach((listener) => listener({ objectId, value, origin }));
    }
  };
  const releaseRegistrations = subscribeRegistrations(registry, {
    topology: (objectId) =>
      topologyListeners.forEach((topologyListener) => topologyListener(objectId)),
    value: (objectId) => notify(objectId, "registration"),
  });
  const applyLocal = async (updates: readonly ControlUpdate[]): Promise<void> => {
    if (updates.length === 0) {
      return;
    }
    applying = true;
    try {
      for (const update of updates) {
        if (!registry.has(update.objectId)) {
          registry.set(update.objectId, update.value);
        }
        registry.broadcastMessage(
          update.objectId,
          { type: "marimo-ui-value-update", value: update.value },
          [],
        );
      }
    } finally {
      applying = false;
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
    controlBindings: readControlBindings,
    subscribeControlBindings,
    subscribeTopology(listener) {
      topologyListeners.add(listener);
      const dispose = () => {
        topologyListeners.delete(listener);
        disposers.delete(dispose);
      };
      disposers.add(dispose);
      return dispose;
    },
    snapshot: () =>
      Array.from(registry.entries, ([objectId, entry]) => ({ objectId, entry }))
        .filter(({ entry }) => isNativeControlValue(entry.value))
        .map(({ objectId, entry }) => ({ objectId, value: entry.value })),
    subscribe(listener) {
      const receive = (event: Event) => {
        const objectId = readyEvents.objectId(event);
        if (objectId) {
          notify(objectId, "input");
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
    applyLocal,
    dispose() {
      Array.from(disposers).forEach((dispose) => dispose());
      releaseRegistrations();
    },
  };
};
