import { z } from "zod";

export const wasmExecutionCellSchema = z.strictObject({
  id: z.string().min(1),
  code: z.string(),
});

export const wasmRuntimeDataSchema = z
  .strictObject({
    code: z.string(),
    filename: z.string(),
    version: z.string(),
    executionCells: z.array(wasmExecutionCellSchema).min(1),
    bootstrapCellId: z.string().min(1),
  })
  .superRefine((data, context) => {
    const ids = data.executionCells.map((cell) => cell.id);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({
        code: "custom",
        path: ["executionCells"],
        message: "WebAssembly execution cells require unique runtime IDs",
      });
    }
    if (ids.filter((id) => id === data.bootstrapCellId).length !== 1) {
      context.addIssue({
        code: "custom",
        path: ["bootstrapCellId"],
        message: "The WebAssembly bootstrap cell must exist in the execution catalog",
      });
    }
  });

export type WasmExecutionCell = z.infer<typeof wasmExecutionCellSchema>;
export type WasmRuntimeData = z.infer<typeof wasmRuntimeDataSchema>;
