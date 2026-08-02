interface UIValueUpdate<TValue> {
  type: "marimo-ui-value-update";
  value: TValue;
}

export interface UIValueRegistry<TId, TValue> {
  has(objectId: TId): boolean;
  set(objectId: TId, value: TValue): void;
  broadcastMessage(
    objectId: TId,
    message: unknown,
    buffers: readonly DataView[],
  ): void;
}

const configuredRegistries = new WeakSet<object>();

const isUIValueUpdate = <TValue>(
  message: unknown,
): message is UIValueUpdate<TValue> =>
  typeof message === "object" &&
  message !== null &&
  "type" in message &&
  message.type === "marimo-ui-value-update" &&
  "value" in message;

/** Retain peer values that arrive while their control is not rendered. */
export const retainUnmountedUIValues = <TId, TValue>(
  registry: UIValueRegistry<TId, TValue>,
) => {
  if (configuredRegistries.has(registry)) {
    return;
  }
  const broadcast = registry.broadcastMessage.bind(registry);
  registry.broadcastMessage = (objectId, message, buffers) => {
    if (!registry.has(objectId) && isUIValueUpdate<TValue>(message)) {
      registry.set(objectId, message.value);
    }
    broadcast(objectId, message, buffers);
  };
  configuredRegistries.add(registry);
};
