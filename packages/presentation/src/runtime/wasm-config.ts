import { z } from "zod";

const selectorPathStepSchema = z.tuple([
  z.enum(["attribute", "item"]),
  z.union([z.string(), z.number()]),
]);

const selectorSpecSchema = z.tuple([z.string(), z.array(selectorPathStepSchema)]);

export const wasmRuntimeDataSchema = z.object({
  code: z.string(),
  filename: z.string(),
  version: z.string(),
  valueSpecs: z.record(z.string(), selectorSpecSchema),
  outputSpecs: z.record(z.string(), selectorSpecSchema),
});

export type WasmRuntimeData = z.infer<typeof wasmRuntimeDataSchema>;

export type WasmProjectionSpecs = Pick<WasmRuntimeData, "outputSpecs" | "valueSpecs">;

const projectionSpecKey = (specs: WasmProjectionSpecs): string =>
  JSON.stringify([specs.valueSpecs, specs.outputSpecs]);

export const createProjectionSpecSynchronizer = (
  initial: WasmProjectionSpecs,
  apply: (specs: WasmProjectionSpecs) => Promise<void>,
): ((specs: WasmProjectionSpecs) => Promise<void>) => {
  let appliedKey = projectionSpecKey(initial);
  let pendingKey: string | undefined;
  let queue: Promise<void> = Promise.resolve();

  return (specs) => {
    const nextKey = projectionSpecKey(specs);
    if (pendingKey === nextKey) {
      return queue;
    }
    if (pendingKey === undefined && appliedKey === nextKey) {
      return Promise.resolve();
    }
    const nextSpecs = {
      valueSpecs: specs.valueSpecs,
      outputSpecs: specs.outputSpecs,
    };
    pendingKey = nextKey;
    const operation = queue
      .catch(() => {})
      .then(() => apply(nextSpecs))
      .then(() => {
        appliedKey = nextKey;
      });
    queue = operation.finally(() => {
      if (pendingKey === nextKey) {
        pendingKey = undefined;
      }
    });
    return queue;
  };
};
