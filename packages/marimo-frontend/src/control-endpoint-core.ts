import { z } from "zod";

interface UIElementEntry {
  value: unknown;
}

export interface UIElementRegistry {
  readonly entries: ReadonlyMap<string, UIElementEntry>;
  has(objectId: string): boolean;
  lookupValue(objectId: string): unknown;
  set(objectId: string, value: unknown): void;
  registerInstance(objectId: string, instance: HTMLElement): void;
  broadcastMessage(objectId: string, message: unknown, buffers: readonly DataView[]): void;
}

export interface ControlUpdate {
  objectId: string;
  value: unknown;
}

export interface ControlEndpoint {
  snapshot(): readonly ControlUpdate[];
  subscribe(listener: (update: ControlUpdate) => void): () => void;
  apply(updates: readonly ControlUpdate[]): Promise<void>;
  dispose(): void;
}

export type SendControlValues = (request: {
  objectIds: string[];
  values: unknown[];
}) => Promise<unknown>;

export interface ReadyEvents {
  type: string;
  objectId(event: Event): string | undefined;
}

const widgetModelReferenceSchema = z.strictObject({ model_id: z.string().min(1) });

const isNativeControlValue = (value: unknown): boolean =>
  !widgetModelReferenceSchema.safeParse(value).success;

type RegistrationSubscriber = (objectId: string) => void;

interface RegistrationBroker {
  readonly original: UIElementRegistry["registerInstance"];
  readonly observeRegistration: UIElementRegistry["registerInstance"];
  readonly subscribers: Set<RegistrationSubscriber>;
}

const registrationBrokers = new WeakMap<UIElementRegistry, RegistrationBroker>();

const subscribeRegistrations = (
  registry: UIElementRegistry,
  subscriber: RegistrationSubscriber,
): (() => void) => {
  let broker = registrationBrokers.get(registry);
  if (!broker) {
    const original = Reflect.get(
      registry,
      "registerInstance",
    ) as UIElementRegistry["registerInstance"];
    const registerInstance = original.bind(registry);
    const subscribers = new Set<RegistrationSubscriber>();
    const observeRegistration: UIElementRegistry["registerInstance"] = (objectId, instance) => {
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
    subscribed = false;
    broker.subscribers.delete(subscriber);
    if (broker.subscribers.size > 0) {
      return;
    }
    if (registry.registerInstance === broker.observeRegistration) {
      registry.registerInstance = broker.original;
    }
    registrationBrokers.delete(registry);
  };
};

export const connectControlEndpoint = (
  document: EventTarget,
  registry: UIElementRegistry,
  readyEvents: ReadyEvents,
  sendControlValues: SendControlValues,
): ControlEndpoint => {
  let applying = false;
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
    async apply(updates) {
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
      await sendControlValues({
        objectIds: updates.map(({ objectId }) => objectId),
        values: updates.map(({ value }) => value),
      });
    },
    dispose() {
      Array.from(disposers).forEach((dispose) => dispose());
      releaseRegistrations();
    },
  };
};
