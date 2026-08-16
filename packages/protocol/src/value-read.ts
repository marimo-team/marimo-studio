import { z } from "zod";

import { jsonValueSchema, type JsonValue } from "./runtime-config.ts";

export const valueReadRequestSchema = z.object({
  revision: z.string().min(1),
  selectors: z.array(z.string()).max(100),
});

export const valueReadErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  hint: z.string().optional(),
});

export const valueReadResponseSchema = z.object({
  values: z.record(z.string(), jsonValueSchema),
  errors: z.record(z.string(), valueReadErrorSchema),
});

export type ValueReadError = z.infer<typeof valueReadErrorSchema>;
export type ValueReadRequest = z.infer<typeof valueReadRequestSchema>;
export type ValueReadResponse = z.infer<typeof valueReadResponseSchema>;

export const parseValueReadResponse = (value: JsonValue): ValueReadResponse => {
  return valueReadResponseSchema.parse(value);
};
