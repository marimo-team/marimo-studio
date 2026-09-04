import { z } from "zod";

export type EmbeddedJsonValue =
  | string
  | number
  | boolean
  | null
  | readonly EmbeddedJsonValue[]
  | { readonly [key: string]: EmbeddedJsonValue };

const recordInputSchema = z.custom<object>(
  (value) =>
    value !== null &&
    Object(value) === value &&
    !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value)),
  { error: "Expected an object record" },
);

export const losslessRecordSchema = <
  KeySchema extends z.ZodType<string>,
  ValueSchema extends z.ZodType,
>(
  keySchema: KeySchema,
  valueSchema: ValueSchema,
) =>
  recordInputSchema.transform<Record<string, z.output<ValueSchema>>>((input, context) => {
    const output: Record<string, z.output<ValueSchema>> = Object.create(null);
    let valid = true;
    for (const [key, value] of Object.entries(input)) {
      const parsedKey = keySchema.safeParse(key);
      const parsedValue = valueSchema.safeParse(value);
      if (!parsedKey.success || !parsedValue.success) {
        valid = false;
        context.addIssue({ code: "custom", input: value, path: [key], message: "Invalid entry" });
        continue;
      }
      output[parsedKey.data] = parsedValue.data;
    }
    return valid ? output : z.NEVER;
  });

export const jsonValueSchema: z.ZodType<EmbeddedJsonValue> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(jsonValueSchema),
    jsonObjectSchema,
  ]),
);

export const jsonObjectSchema: z.ZodType<Readonly<Record<string, EmbeddedJsonValue>>> =
  losslessRecordSchema(z.string(), jsonValueSchema);

export const parseEmbeddedJsonValue = <Value>(value: Value): EmbeddedJsonValue =>
  jsonValueSchema.parse(value);
