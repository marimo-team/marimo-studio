import { z } from "zod";

import type { JsonValue } from "./runtime-config.ts";

import { valueReadErrorSchema } from "./value-read.ts";

export const MAX_OUTPUT_SELECTORS = 100;

export const outputReadRequestSchema = z
  .object({
    revision: z.string().min(1),
    selectors: z.array(z.string()).max(MAX_OUTPUT_SELECTORS),
    activeSelectors: z.array(z.string()).max(MAX_OUTPUT_SELECTORS),
  })
  .refine(
    ({ selectors, activeSelectors }) =>
      selectors.every((selector) => activeSelectors.includes(selector)),
    { message: "Every requested selector must also be active.", path: ["selectors"] },
  );

export const renderedOutputSchema = z
  .object({
    ownerCellId: z.string().min(1),
    mimetype: z.string().min(1),
    data: z.string(),
    timestamp: z.number(),
    resetUiObjectIds: z.array(z.string().min(1)),
  })
  .refine(
    ({ ownerCellId, resetUiObjectIds }) =>
      resetUiObjectIds.every((objectId) => objectId.startsWith(`${ownerCellId}-`)),
    {
      message: "A projected output may reset only UI objects owned by its projection.",
      path: ["resetUiObjectIds"],
    },
  );

export const outputReadResponseSchema = z.object({
  outputs: z.record(z.string(), renderedOutputSchema),
  errors: z.record(z.string(), valueReadErrorSchema),
});

export type OutputReadRequest = z.infer<typeof outputReadRequestSchema>;
export type OutputReadResponse = z.infer<typeof outputReadResponseSchema>;
export type RenderedOutput = z.infer<typeof renderedOutputSchema>;

export const parseOutputReadResponse = (value: JsonValue): OutputReadResponse => {
  return outputReadResponseSchema.parse(value);
};
