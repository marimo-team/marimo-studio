import { z } from "zod";

export interface UIValueRegistry<TId> {
  has(objectId: TId): boolean;
  set(objectId: TId, value: unknown): void;
  broadcastMessage(objectId: TId, message: unknown, buffers: readonly DataView[]): void;
}

const configuredRegistries = new WeakSet<object>();

const uiValueUpdateSchema = z.object({
  type: z.literal("marimo-ui-value-update"),
  value: z.unknown().nonoptional(),
});

/** Retain peer values that arrive while their control is not rendered. */
export const retainUnmountedUIValues = <TId>(registry: UIValueRegistry<TId>) => {
  if (configuredRegistries.has(registry)) {
    return;
  }
  const broadcast = registry.broadcastMessage.bind(registry);
  registry.broadcastMessage = (objectId, message, buffers) => {
    const update = uiValueUpdateSchema.safeParse(message);
    if (!registry.has(objectId) && update.success) {
      registry.set(objectId, update.data.value);
    }
    broadcast(objectId, message, buffers);
  };
  configuredRegistries.add(registry);
};
