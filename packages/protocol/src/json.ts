import { z } from "zod";

import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema, type JsonValue } from "./runtime-config.ts";

export { jsonValueSchema, type JsonValue } from "./runtime-config.ts";

export type JsonObject = Readonly<Record<string, JsonValue>>;

export const jsonObjectSchema: z.ZodType<JsonObject> = ownRecordSchema(z.string(), jsonValueSchema);

export const losslessRecordSchema = ownRecordSchema;

export const parseJsonValue = <Value>(value: Value): JsonValue => jsonValueSchema.parse(value);

export const parseJsonObject = <Value>(value: Value): JsonObject => jsonObjectSchema.parse(value);

export const parseJson = (source: string): JsonValue => parseJsonValue(JSON.parse(source));

export const jsonCodec = <T extends z.core.$ZodType>(schema: T) =>
  z.codec(z.string(), schema, {
    decode: (source, context) => {
      try {
        return JSON.parse(source);
      } catch (error: unknown) {
        context.issues.push({
          code: "invalid_format",
          format: "json",
          input: source,
          message: error instanceof Error ? error.message : "Invalid JSON",
        });
        return z.NEVER;
      }
    },
    encode: (value) => JSON.stringify(value),
  });
