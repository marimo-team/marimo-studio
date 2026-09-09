import { z } from "zod";

import { jsonValueSchema, type JsonValue } from "./runtime-config.ts";

const optionalString = z.string().optional().catch(undefined);
const optionalBoolean = z.boolean().optional().catch(undefined);

export const errorResponseSchema = z
  .object({
    error: optionalString,
    message: optionalString,
    hint: optionalString,
    transient: optionalBoolean,
    revision: optionalString,
    external_recovery: optionalString,
  })
  .catchall(jsonValueSchema);

export type ErrorResponse = z.infer<typeof errorResponseSchema>;

export const parseErrorResponse = (value: JsonValue): ErrorResponse => {
  const result = errorResponseSchema.safeParse(value);
  if (!result.success) return {};
  return Object.fromEntries(Object.entries(result.data).filter(([, field]) => field !== undefined));
};
