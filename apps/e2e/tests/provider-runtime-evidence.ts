import { observedProjectionInstanceSchema } from "@marimo-studio/protocol/projections";
import { z } from "zod";

export const providerProjectionSchema = observedProjectionInstanceSchema;

export const readyCellProjectionSchema = observedProjectionInstanceSchema.safeExtend({
  mountId: z.string().min(1),
  runtimeCellId: z.string().min(1),
  phase: z.literal("ready"),
  error: z.null(),
});

export const failedCellProjectionSchema = observedProjectionInstanceSchema.safeExtend({
  runtimeCellId: z.null(),
  phase: z.enum(["missing", "error"]),
  error: z.strictObject({ code: z.string().min(1), message: z.string() }),
});

export type ProviderProjection = z.infer<typeof providerProjectionSchema>;
export type ReadyCellProjection = z.infer<typeof readyCellProjectionSchema>;
