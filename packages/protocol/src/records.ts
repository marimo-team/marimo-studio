import { z } from "zod";

const recordInputSchema = z.custom<object>(
  (value) => {
    if (value === null || Object(value) !== value || Array.isArray(value)) {
      return false;
    }
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  },
  { error: "Expected an object record" },
);

export const ownRecordSchema = <ValueSchema extends z.ZodType>(
  keySchema: z.ZodType<string>,
  valueSchema: ValueSchema,
) =>
  recordInputSchema.transform<Record<string, z.output<ValueSchema>>>((input, context) => {
    const output: Record<string, z.output<ValueSchema>> = Object.create(null);
    let valid = true;
    for (const [key, value] of Object.entries(input)) {
      const parsedKey = keySchema.safeParse(key);
      if (!parsedKey.success) {
        valid = false;
        parsedKey.error.issues.forEach((issue) =>
          context.addIssue({ ...issue, path: [key, ...issue.path] }),
        );
        continue;
      }
      const parsedValue = valueSchema.safeParse(value);
      if (!parsedValue.success) {
        valid = false;
        parsedValue.error.issues.forEach((issue) =>
          context.addIssue({ ...issue, path: [key, ...issue.path] }),
        );
        continue;
      }
      output[parsedKey.data] = parsedValue.data;
    }
    return valid ? output : z.NEVER;
  });
