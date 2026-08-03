import { z } from "zod";

import { jsonValueSchema } from "./runtime-config.ts";

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
export type ValueReadResponse = z.infer<typeof valueReadResponseSchema>;

export const parseValueReadResponse = (value: unknown): ValueReadResponse => {
  return valueReadResponseSchema.parse(value);
};
