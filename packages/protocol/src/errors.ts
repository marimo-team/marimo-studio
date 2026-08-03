import { z } from "zod";

const optionalString = z.string().optional().catch(undefined);
const optionalBoolean = z.boolean().optional().catch(undefined);

export const errorResponseSchema = z.object({
  error: optionalString,
  message: optionalString,
  hint: optionalString,
  transient: optionalBoolean,
  revision: optionalString,
});

export type ErrorResponse = z.infer<typeof errorResponseSchema>;

export const parseErrorResponse = (value: unknown): ErrorResponse => {
  const result = errorResponseSchema.safeParse(value);
  return result.success ? result.data : {};
};
