import { z } from "zod";

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
