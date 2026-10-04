import { z } from "zod";

import { errorResponseSchema } from "./errors.ts";
import { jsonValueSchema } from "./runtime-config.ts";
import { runtimeProgressSchema } from "./runtime-progress.ts";

export const RUNTIME_CONFIG_STREAM_TYPE = "application/x-ndjson";
export const RUNTIME_CONFIG_STREAM_MAX_LINE_BYTES = 16 * 1_024 * 1_024 + 64 * 1_024;

export const runtimeConfigPacketSchema = z.discriminatedUnion("type", [
  z.strictObject({ type: z.literal("progress"), progress: runtimeProgressSchema }),
  // `parseRuntimeConfig()` validates the record and resolves its URLs against
  // the response that carried the stream.
  z.strictObject({ type: z.literal("config"), config: jsonValueSchema }),
  errorResponseSchema.extend({
    type: z.literal("error"),
    error: z.string().min(1),
    message: z.string().min(1),
    hint: z.string().optional(),
    transient: z.boolean().optional(),
  }),
]);
