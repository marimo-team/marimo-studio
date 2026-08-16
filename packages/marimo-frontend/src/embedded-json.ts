import { z } from "zod";

export type EmbeddedJsonValue =
  | null
  | boolean
  | number
  | string
  | readonly EmbeddedJsonValue[]
  | { readonly [key: string]: EmbeddedJsonValue };

const embeddedJsonValueSchema: z.ZodType<EmbeddedJsonValue> = z.lazy(() =>
  z.union([
    z.null(),
    z.boolean(),
    z.number(),
    z.string(),
    z.array(embeddedJsonValueSchema),
    z.record(z.string(), embeddedJsonValueSchema),
  ]),
);

export const parseEmbeddedJsonValue = (value: z.input<typeof embeddedJsonValueSchema>) =>
  embeddedJsonValueSchema.parse(value);
