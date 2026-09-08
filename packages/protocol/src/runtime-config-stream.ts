import { z } from "zod";

import { runtimeConfigSchema } from "./runtime-config.ts";
import { runtimeProgressSchema } from "./runtime-progress.ts";

export const RUNTIME_CONFIG_STREAM_TYPE = "application/x-ndjson";
export const RUNTIME_CONFIG_STREAM_MAX_LINE_BYTES = 16 * 1_024 * 1_024 + 64 * 1_024;

export const runtimeConfigPacketSchema = z.discriminatedUnion("type", [
  z.strictObject({ type: z.literal("progress"), progress: runtimeProgressSchema }),
  z.strictObject({ type: z.literal("config"), config: runtimeConfigSchema }),
  z.object({
    type: z.literal("error"),
    error: z.string().min(1),
    message: z.string().min(1),
    hint: z.string().optional(),
    transient: z.boolean().optional(),
  }),
]);
