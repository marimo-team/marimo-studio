import { z } from "zod";

import { MAX_ACTIVE_PROJECTION_INSTANCES, projectionRequestSchema } from "./projections.ts";
import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema, type JsonValue } from "./runtime-config.ts";

export const valueReadRequestSchema = z.object({
  revision: z.string().min(1),
  projections: z.array(projectionRequestSchema).max(MAX_ACTIVE_PROJECTION_INSTANCES),
});

export const valueReadErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  hint: z.string().optional(),
});

export const valueReadResponseSchema = z.object({
  values: ownRecordSchema(z.string(), jsonValueSchema),
  errors: ownRecordSchema(z.string(), valueReadErrorSchema),
});

export type ValueReadError = z.infer<typeof valueReadErrorSchema>;
export type ValueReadRequest = z.infer<typeof valueReadRequestSchema>;
export type ValueReadResponse = z.infer<typeof valueReadResponseSchema>;

export const parseValueReadResponse = (value: JsonValue): ValueReadResponse => {
  return valueReadResponseSchema.parse(value);
};
