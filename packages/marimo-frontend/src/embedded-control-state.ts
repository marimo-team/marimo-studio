import { z } from "zod";

export interface EmbeddedControlRegistry<TId> {
  has(objectId: TId): boolean;
  set(objectId: TId, value: unknown): void;
  broadcastMessage(objectId: TId, message: unknown, buffers: readonly DataView[]): void;
}

const configuredRegistries = new WeakSet<object>();
const controlUpdateSchema = z.object({
  type: z.literal("marimo-ui-value-update"),
  value: z.unknown().nonoptional(),
});

export const retainUnmountedControlValues = <TId>(registry: EmbeddedControlRegistry<TId>): void => {
  if (configuredRegistries.has(registry)) {
    return;
  }
  const broadcast = registry.broadcastMessage.bind(registry);
  registry.broadcastMessage = (objectId, message, buffers) => {
    const update = controlUpdateSchema.safeParse(message);
    if (!registry.has(objectId) && update.success) {
      registry.set(objectId, update.data.value);
    }
    broadcast(objectId, message, buffers);
  };
  configuredRegistries.add(registry);
};
