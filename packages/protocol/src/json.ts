import { parsePortableJson } from "@marimo-team/portable-json";
import { z } from "zod";

export {
  MAX_JSON_DEPTH,
  MAX_JSON_VALUES,
  type JsonObject,
  type JsonValue,
} from "@marimo-team/portable-json";
export {
  jsonObjectSchema,
  jsonValueSchema,
  losslessRecordSchema,
} from "@marimo-team/portable-json/zod";
export { parsePortableJson };

export const jsonCodec = <T extends z.core.$ZodType>(schema: T) =>
  z.codec(z.string(), schema, {
    decode: (source, context) => {
      try {
        // SAFETY: The codec's output schema validates the parsed portable value immediately.
        return parsePortableJson(source) as z.input<T>;
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
